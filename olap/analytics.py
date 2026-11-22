from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field, model_validator

JOIN_SALES = """
    FROM fact_sales f
    JOIN dim_date d USING (date_key)
    JOIN dim_store s USING (store_key)
    JOIN dim_product p USING (product_key)
"""
JOIN_INVENTORY = JOIN_SALES.replace("fact_sales", "fact_inventory_snapshot")
CUBE_LIMIT = 4000
Axis = Literal["year", "quarter", "month", "day", "region", "store", "category", "product"]
AXES = {
    "year": ("lpad(d.year::text, 4, '0')", "lpad(d.year::text, 4, '0')"),
    "quarter": ("lpad(d.year::text, 4, '0') || '-Q' || d.quarter",
                "lpad(d.year::text, 4, '0') || '-Q' || d.quarter"),
    "month": ("to_char(d.full_date, 'YYYY-MM')", "to_char(d.full_date, 'YYYY-MM')"),
    "day": ("to_char(d.full_date, 'YYYY-MM-DD')", "to_char(d.full_date, 'YYYY-MM-DD')"),
    "region": ("s.region", "s.region"),
    "store": ("s.store_id", "s.store_name"),
    "category": ("p.category", "p.category"),
    "product": ("p.product_id", "p.product_name"),
}
FACT_METRICS = {
    "sales": {
        "net_sales": "SUM(f.net_sales_amount)",
        "units_sold": "SUM(f.quantity_sold)",
        "sales_lines": "COUNT(*)",
    },
    "inventory": {
        "stock": "SUM(f.stock_on_hand)",
        "below_reorder": "COUNT(*) FILTER (WHERE f.stock_on_hand < f.reorder_point)",
        "out_of_stock": "COUNT(*) FILTER (WHERE f.stock_on_hand = 0)",
    },
}


class Filters(BaseModel):
    start: date
    end: date
    region: list[str] = Field(default_factory=list, max_length=150)
    store: list[str] = Field(default_factory=list, max_length=150)
    category: list[str] = Field(default_factory=list, max_length=150)
    product: list[str] = Field(default_factory=list, max_length=150)

    @model_validator(mode="after")
    def check_dates(self):
        if self.start > self.end:
            raise ValueError("Start date must be on or before end date")
        return self


class CubeRequest(Filters):
    fact: Literal["sales", "inventory"] = "sales"
    metric: Literal["net_sales", "units_sold", "sales_lines", "stock", "below_reorder", "out_of_stock"] = "net_sales"
    rows: Axis = "month"
    columns: Axis | None = None

    @model_validator(mode="after")
    def check_axes(self):
        if self.rows == self.columns:
            raise ValueError("Choose different row and column dimensions")
        if self.metric not in FACT_METRICS[self.fact]:
            raise ValueError("The measure must belong to the selected dataset")
        if self.fact == "inventory" and any(
            axis in {"year", "quarter", "month", "day"} for axis in (self.rows, self.columns)
        ):
            raise ValueError("Inventory uses a single snapshot date. Group by a product or store dimension.")
        return self


def date_key(value):
    return value.year * 10000 + value.month * 100 + value.day


def filter_clause(filters, *, start=None, end=None, snapshot=None):
    if snapshot is None:
        where = ["f.date_key BETWEEN %s AND %s"]
        arguments = [date_key(start or filters.start), date_key(end or filters.end)]
    else:
        where = ["f.date_key = %s"]
        arguments = [snapshot]
    for field in ("region", "store", "category", "product"):
        values = getattr(filters, field)
        if values:
            where.append(f"{AXES[field][0]} = ANY(%s)")
            arguments.append(values)
    return " WHERE " + " AND ".join(where), arguments


def get_refresh(cursor):
    cursor.execute("""
        SELECT source.name, batch.batch_id, batch.finished_at, batch.status
        FROM (VALUES ('sales', 'sales_rows'), ('inventory', 'inventory_rows')) source(name, counter)
        JOIN LATERAL (
            SELECT batch_id, finished_at, status
            FROM etl_run
            WHERE status IN ('loaded', 'loaded_with_rejects')
                AND (summary -> 'reconciliation' ->> source.counter)::bigint > 0
            ORDER BY finished_at DESC, run_id DESC LIMIT 1
        ) batch ON TRUE
    """)
    return {row["name"]: row for row in cursor}


def metadata(cursor):
    cursor.execute("""
        SELECT MIN(full_date) AS first_date, MAX(full_date) AS last_date FROM dim_date
    """)
    dates = cursor.fetchone()
    cursor.execute("SELECT DISTINCT region FROM dim_store ORDER BY region")
    regions = [row["region"] for row in cursor]
    cursor.execute("SELECT DISTINCT category FROM dim_product ORDER BY category")
    categories = [row["category"] for row in cursor]
    cursor.execute("SELECT store_id AS id, store_name AS name, region FROM dim_store ORDER BY store_name")
    stores = cursor.fetchall()
    cursor.execute("SELECT product_id AS id, product_name AS name, category FROM dim_product ORDER BY product_name")
    products = cursor.fetchall()
    return {
        **dates, "regions": regions, "categories": categories, "stores": stores,
        "products": products, "refresh": get_refresh(cursor),
    }


def snapshot_date(cursor, filters):
    cursor.execute("""
        SELECT MAX(date_key) AS key FROM fact_inventory_snapshot WHERE date_key BETWEEN %s AND %s
    """, (date_key(filters.start), date_key(filters.end)))
    key = cursor.fetchone()["key"]
    if key is None:
        return None, None
    day = date(key // 10000, key // 100 % 100, key % 100)
    return key, day


def inventory_totals(cursor, filters):
    key, day = snapshot_date(cursor, filters)
    if key is None:
        return {"snapshot_date": None, "stock": 0, "below_reorder": 0, "out_of_stock": 0, "positions": 0}, None
    where, values = filter_clause(filters, snapshot=key)
    cursor.execute(f"""
        SELECT COALESCE(SUM(f.stock_on_hand),0) AS stock,
            COUNT(*) FILTER (WHERE f.stock_on_hand < f.reorder_point) AS below_reorder,
            COUNT(*) FILTER (WHERE f.stock_on_hand = 0) AS out_of_stock, COUNT(*) AS positions
        {JOIN_INVENTORY} {where}
    """, values)
    return {"snapshot_date": day, **cursor.fetchone()}, (where, values)


def sales_dashboard(cursor, filters):
    where, values = filter_clause(filters)
    cursor.execute(f"""
        SELECT to_char(d.full_date, 'YYYY-MM') AS period,
            SUM(f.net_sales_amount) AS net_sales, SUM(f.quantity_sold) AS units_sold, COUNT(*) AS sales_lines
        {JOIN_SALES} {where}
        GROUP BY 1 ORDER BY 1
    """, values)
    trend = cursor.fetchall()
    totals = {measure: sum(row[measure] for row in trend) for measure in FACT_METRICS["sales"]}

    previous = None
    length = (filters.end - filters.start).days + 1
    previous_start_ordinal = filters.start.toordinal() - length
    if previous_start_ordinal >= 1:
        prior_where, prior_values = filter_clause(
            filters, start=date.fromordinal(previous_start_ordinal), end=filters.start - timedelta(days=1),
        )
        cursor.execute(f"""
            SELECT SUM(f.net_sales_amount) AS net_sales, SUM(f.quantity_sold) AS units_sold, COUNT(*) AS sales_lines
            {JOIN_SALES} {prior_where}
        """, prior_values)
        row = cursor.fetchone()
        if row["sales_lines"]:
            previous = row

    cursor.execute(f"""
        SELECT s.region, SUM(f.net_sales_amount) AS net_sales, SUM(f.quantity_sold) AS units_sold
        {JOIN_SALES} {where}
        GROUP BY s.region ORDER BY net_sales DESC, s.region
    """, values)
    regions = cursor.fetchall()
    cursor.execute(f"""
        SELECT p.category, SUM(f.net_sales_amount) AS net_sales,
            SUM(f.quantity_sold) AS units_sold, COUNT(*) AS sales_lines,
            COUNT(DISTINCT f.product_key) AS products
        {JOIN_SALES} {where}
        GROUP BY p.category ORDER BY net_sales DESC, p.category
    """, values)
    categories = cursor.fetchall()
    inventory, _ = inventory_totals(cursor, filters)
    return {
        "totals": {**totals, **inventory}, "previous": previous,
        "trend": trend, "regions": regions, "categories": categories,
    }


def inventory_dashboard(cursor, filters):
    totals, query_parts = inventory_totals(cursor, filters)
    if query_parts is None:
        return {"totals": totals, "categories": [], "exceptions": []}
    where, values = query_parts
    cursor.execute(f"""
        SELECT p.category, SUM(f.stock_on_hand) AS stock,
            COUNT(*) FILTER (WHERE f.stock_on_hand < f.reorder_point) AS below_reorder
        {JOIN_INVENTORY} {where}
        GROUP BY p.category ORDER BY stock DESC, p.category
    """, values)
    categories = cursor.fetchall()
    cursor.execute(f"""
        SELECT p.product_name, p.category, s.store_name, s.region, f.stock_on_hand, f.reorder_point,
            f.reorder_point - f.stock_on_hand AS shortage
        {JOIN_INVENTORY} {where}
            AND f.stock_on_hand < f.reorder_point
        ORDER BY shortage DESC, p.product_name, s.store_name, p.product_id, s.store_id
        LIMIT 100
    """, values)
    return {"totals": totals, "categories": categories, "exceptions": cursor.fetchall()}


def cube(cursor, request):
    day = None
    if request.fact == "inventory":
        key, day = snapshot_date(cursor, request)
        if key is None:
            return {"cells": [], "snapshot_date": None}
        where, values = filter_clause(request, snapshot=key)
        joins = JOIN_INVENTORY
    else:
        where, values = filter_clause(request)
        joins = JOIN_SALES

    row_key, row_label = AXES[request.rows]
    selection = f"{row_key} AS row_key, {row_label} AS row_label"
    groups = "1, 2"
    if request.columns:
        column_key, column_label = AXES[request.columns]
        selection += f", {column_key} AS column_key, {column_label} AS column_label"
        groups += ", 3, 4"
    aggregate = FACT_METRICS[request.fact][request.metric]
    cursor.execute(f"""
        SELECT {selection}, {aggregate} AS value
        {joins} {where}
        GROUP BY {groups} ORDER BY {groups} LIMIT %s
    """, (*values, CUBE_LIMIT + 1))
    cells = cursor.fetchall()
    row_count = len({cell["row_key"] for cell in cells})
    column_count = len({cell.get("column_key") for cell in cells})
    if len(cells) > CUBE_LIMIT or row_count * column_count > CUBE_LIMIT:
        raise ValueError(f"This query exceeds {CUBE_LIMIT:,} grouped cells. Narrow the filters or use a higher level.")
    return {"cells": cells, "snapshot_date": day}
