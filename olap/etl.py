import csv
import re
import time
from collections import Counter
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json, RealDictCursor, execute_values

from .db import connect

LOAD_LOCK = 141404
BATCH_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}")
FILES = {
    "products": ("product_id", "product_name", "category"),
    "stores": ("store_id", "store_name", "region"),
    "sales": ("sales_line_key", "date", "store_id", "product_id", "quantity_sold", "net_sales_amount"),
    "inventory": ("date", "store_id", "product_id", "stock_on_hand", "reorder_point"),
}
IDENTIFIERS = {"product_id", "store_id"}
TEXT_LENGTHS = {"product_name": 150, "store_name": 150, "category": 80, "region": 80}


def normalize(field, raw):
    if raw is None or not (value := raw.strip()) or "\0" in value:
        raise ValueError(f"{field} is missing or invalid")
    if field in IDENTIFIERS or field in TEXT_LENGTHS:
        if len(value) > TEXT_LENGTHS.get(field, 40):
            raise ValueError(f"{field} exceeds its maximum length")
        return value
    if field == "date":
        try:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                raise ValueError("invalid date format")
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("date must be a valid YYYY-MM-DD value") from exc
    if field == "net_sales_amount":
        if not re.fullmatch(r"[0-9]{1,12}(\.[0-9]{1,2})?", value):
            raise ValueError("net_sales_amount must be a nonnegative CAD amount with at most two decimal places")
        return Decimal(value)
    maximum = 2**63 - 1 if field == "sales_line_key" else 2**31 - 1
    if not re.fullmatch(r"[0-9]{1,19}", value) or int(value) > maximum:
        raise ValueError(f"{field} must be a nonnegative integer in range")
    if field == "sales_line_key" and int(value) == 0:
        raise ValueError("sales_line_key must be positive")
    return int(value)


def read_rows(directory, source, fields, rejects):
    path = directory / f"{source}.csv"
    parsed = []
    extracted = 0
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        if len(reader.fieldnames or ()) != len(fields) or set(reader.fieldnames or ()) != set(fields):
            raise ValueError(f"{path.name} must contain headers {', '.join(fields)}")
        for raw in reader:
            extracted += 1
            try:
                if None in raw:
                    raise ValueError("row has more columns than the header")
                values = tuple(normalize(field, raw[field]) for field in fields)
                parsed.append((reader.line_num, raw, values))
            except ValueError as exc:
                rejects.append(rejection(source, reader.line_num, str(exc), raw))

    key_length = 3 if source == "inventory" else 1
    keys = Counter(values[:key_length] for _, _, values in parsed)
    accepted = []
    for line, raw, values in parsed:
        if keys[values[:key_length]] > 1:
            rejects.append(rejection(source, line, "duplicate key in batch", raw))
        else:
            accepted.append((line, raw, values))
    return extracted, accepted


def rejection(source, line, reason, raw):
    # PostgreSQL JSONB cannot store NUL even when it is JSON-escaped.
    def clean(value):
        return value.replace("\0", "\\0") if isinstance(value, str) else value

    data = {
        clean(str(key)): [clean(part) for part in value] if isinstance(value, list) else clean(value)
        for key, value in raw.items()
    }
    return (f"{source}.csv", line, reason, Json(data))


def upsert_dimensions(cursor, records):
    for source, table, identifier, attributes in (
        ("products", "dim_product", "product_id", ("product_name", "category")),
        ("stores", "dim_store", "store_id", ("store_name", "region")),
    ):
        statement = sql.SQL("""
            INSERT INTO {} ({}) VALUES %s
            ON CONFLICT ({}) DO UPDATE SET {}
        """).format(
            sql.Identifier(table),
            sql.SQL(", ").join(map(sql.Identifier, (identifier, *attributes))),
            sql.Identifier(identifier),
            sql.SQL(", ").join(
                sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(name), sql.Identifier(name))
                for name in attributes
            ),
        )
        execute_values(cursor, statement, [row[2] for row in records[source]], page_size=1000)


def resolve_facts(cursor, records, rejects):
    cursor.execute("SELECT product_id FROM dim_product")
    products = {row[0] for row in cursor}
    cursor.execute("SELECT store_id FROM dim_store")
    stores = {row[0] for row in cursor}
    facts = {}
    for source in ("sales", "inventory"):
        offsets = slice(2, 4) if source == "sales" else slice(1, 3)
        values = []
        for line, raw, row in records[source]:
            store_id, product_id = row[offsets]
            if store_id not in stores or product_id not in products:
                rejects.append(rejection(source, line, "unknown store_id or product_id", raw))
            else:
                values.append(row)
        facts[source] = values
    return facts


def stage_facts(cursor, facts):
    cursor.execute("""
        CREATE TEMP TABLE stage_sales (
            sales_line_key bigint, full_date date, store_id text, product_id text,
            quantity_sold integer, net_sales_amount numeric(14,2)
        ) ON COMMIT DROP;
        CREATE TEMP TABLE stage_inventory (
            full_date date, store_id text, product_id text, stock_on_hand integer, reorder_point integer
        ) ON COMMIT DROP;
    """)
    execute_values(cursor, "INSERT INTO stage_sales VALUES %s", facts["sales"], page_size=2000)
    execute_values(cursor, "INSERT INTO stage_inventory VALUES %s", facts["inventory"], page_size=2000)
    cursor.execute("""
        ANALYZE stage_sales;
        ANALYZE stage_inventory;
        INSERT INTO dim_date (date_key, full_date, year, quarter, month)
        SELECT to_char(full_date, 'YYYYMMDD')::int, full_date,
               EXTRACT(YEAR FROM full_date), EXTRACT(QUARTER FROM full_date), EXTRACT(MONTH FROM full_date)
        FROM (SELECT full_date FROM stage_sales UNION SELECT full_date FROM stage_inventory) dates
        ON CONFLICT (date_key) DO NOTHING;

        CREATE TEMP TABLE mapped_sales ON COMMIT DROP AS
        SELECT sales_line_key, d.date_key, s.store_key, p.product_key, quantity_sold, net_sales_amount
        FROM stage_sales
        JOIN dim_date d USING (full_date)
        JOIN dim_store s USING (store_id)
        JOIN dim_product p USING (product_id);

        CREATE TEMP TABLE mapped_inventory ON COMMIT DROP AS
        SELECT d.date_key, s.store_key, p.product_key, stock_on_hand, reorder_point
        FROM stage_inventory
        JOIN dim_date d USING (full_date)
        JOIN dim_store s USING (store_id)
        JOIN dim_product p USING (product_id);

        ANALYZE mapped_sales;
        ANALYZE mapped_inventory;
        INSERT INTO fact_sales (sales_line_key, date_key, store_key, product_key, quantity_sold, net_sales_amount)
        SELECT * FROM mapped_sales
        ON CONFLICT (sales_line_key) DO UPDATE SET
            date_key = EXCLUDED.date_key, store_key = EXCLUDED.store_key, product_key = EXCLUDED.product_key,
            quantity_sold = EXCLUDED.quantity_sold, net_sales_amount = EXCLUDED.net_sales_amount
        WHERE fact_sales IS DISTINCT FROM EXCLUDED;

        INSERT INTO fact_inventory_snapshot (date_key, store_key, product_key, stock_on_hand, reorder_point)
        SELECT * FROM mapped_inventory
        ON CONFLICT (date_key, store_key, product_key) DO UPDATE SET
            stock_on_hand = EXCLUDED.stock_on_hand, reorder_point = EXCLUDED.reorder_point
        WHERE (fact_inventory_snapshot.stock_on_hand, fact_inventory_snapshot.reorder_point)
            IS DISTINCT FROM (EXCLUDED.stock_on_hand, EXCLUDED.reorder_point);
    """)


def reconcile(cursor, facts):
    cursor.execute("""
        SELECT COUNT(*), COALESCE(SUM(f.net_sales_amount), 0)
        FROM mapped_sales m
        JOIN fact_sales f USING (sales_line_key, date_key, store_key, product_key, quantity_sold, net_sales_amount)
    """)
    sales_rows, sales_total = cursor.fetchone()
    cursor.execute("""
        SELECT COUNT(*), COALESCE(SUM(i.stock_on_hand), 0)
        FROM mapped_inventory m
        JOIN fact_inventory_snapshot i USING (date_key, store_key, product_key, stock_on_hand, reorder_point)
    """)
    inventory_rows, stock_total = cursor.fetchone()
    sources = (len(facts["sales"]), sum(row[5] for row in facts["sales"]),
               len(facts["inventory"]), sum(row[3] for row in facts["inventory"]))
    if (sales_rows, sales_total, inventory_rows, stock_total) != sources:
        raise ValueError("source and warehouse reconciliation failed")
    return {
        "sales_rows": sales_rows, "net_sales": f"{sales_total:.2f}",
        "inventory_rows": inventory_rows, "stock_across_source_rows": stock_total,
    }


def apply_batch(cursor, directory, run_id):
    rejects, records, counts = [], {}, {}
    for source, fields in FILES.items():
        extracted, records[source] = read_rows(directory, source, fields, rejects)
        counts[source] = {"extracted": extracted}

    upsert_dimensions(cursor, records)
    facts = resolve_facts(cursor, records, rejects)
    stage_facts(cursor, facts)
    reconciliation = reconcile(cursor, facts)
    for source, counts_by_source in counts.items():
        accepted = len(facts[source] if source in facts else records[source])
        counts_by_source.update(accepted=accepted, rejected=counts_by_source["extracted"] - accepted)

    execute_values(cursor, """
        INSERT INTO etl_reject (run_id, source_file, line_number, reason, source_row) VALUES %s
    """, [(run_id, *item) for item in rejects], page_size=500)
    status = "loaded_with_rejects" if rejects else "loaded"
    summary = {"sources": counts, "rejected": len(rejects), "reconciliation": reconciliation}
    cursor.execute("""
        UPDATE etl_run SET status = %s, summary = %s, finished_at = clock_timestamp()
        WHERE run_id = %s
    """, (status, Json(summary), run_id))
    return {"run_id": run_id, "batch_id": directory.name, "status": status, "summary": summary}


def load_batch(directory):
    directory = Path(directory)
    batch_id = directory.name
    if not BATCH_ID.fullmatch(batch_id) or not (directory / "READY").is_file():
        raise ValueError("batch directory needs a valid ID and a READY marker")

    with closing(connect("ETL_DATABASE_URL")) as conn:
        with conn, conn.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", (LOAD_LOCK,))
            cursor.execute("""
                UPDATE etl_run SET status = 'failed', error = 'Previous worker stopped before finishing',
                    finished_at = clock_timestamp() WHERE status = 'running'
            """)
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT run_id, batch_id, status, summary FROM etl_run
                WHERE batch_id = %s AND status IN ('loaded', 'loaded_with_rejects')
                ORDER BY run_id DESC LIMIT 1
            """, (batch_id,))
            if previous := cursor.fetchone():
                return {**previous, "already_loaded": True}
            cursor.execute("INSERT INTO etl_run (batch_id) VALUES (%s) RETURNING run_id", (batch_id,))
            run_id = cursor.fetchone()["run_id"]

        try:
            with conn, conn.cursor() as cursor:
                return apply_batch(cursor, directory, run_id)
        except Exception as exc:
            with conn, conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE etl_run SET status = 'failed', error = %s, finished_at = clock_timestamp()
                    WHERE run_id = %s
                """, (str(exc)[:2000], run_id))
            raise


def load_with_retry(directory):
    for attempt in range(3):
        try:
            return load_batch(directory)
        except (psycopg2.OperationalError, psycopg2.errors.SerializationFailure, psycopg2.errors.DeadlockDetected):
            if attempt == 2:
                raise
            time.sleep(2**attempt)
