import csv
import os
from contextlib import closing
from decimal import Decimal
from uuid import uuid4

import psycopg2
import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from olap.__main__ import add_account
from olap.app import app
from olap.db import connect, initialize
from olap.etl import FILES, load_batch

PASSWORD = "sample test password"
FILTERS = {"start": "2026-10-31", "end": "2026-11-01"}


def write_batch(path, **rows_by_source):
    path.mkdir()
    for source, columns in FILES.items():
        with (path / f"{source}.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(columns)
            writer.writerows(rows_by_source.get(source, ()))
    (path / "READY").touch()
    return path


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory):
    dsn = os.environ.get("OLAP_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set OLAP_TEST_DATABASE_URL to run PostgreSQL integration tests.")
    schema = f"olap_test_{uuid4().hex}"
    directory = tmp_path_factory.mktemp("batches")
    with pytest.MonkeyPatch.context() as patch, closing(psycopg2.connect(dsn)) as owner:
        created = sql.Identifier(schema)
        with owner, owner.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE SCHEMA {}").format(created))
        try:
            patch.setenv("DATABASE_URL", make_dsn(dsn, options=f"-c search_path={schema}"))
            for name in ("ETL_DATABASE_URL", "OLAP_WEB_DB_PASSWORD", "OLAP_ETL_DB_PASSWORD"):
                patch.delenv(name, raising=False)
            with closing(connect()) as conn:
                initialize(conn)
                add_account(conn, "manager", "manager", PASSWORD)
                add_account(conn, "admin", "admin", PASSWORD)
            rows = {
                "products": [("P1", "Lamp", "Lighting"), ("P2", "Chair", "Furniture")],
                "stores": [("S1", "Ottawa", "East"), ("S2", "Calgary", "West")],
                "sales": [
                    (1, "2026-10-31", "S1", "P1", 2, "10.25"),
                    (2, "2026-11-01", "S1", "P2", 1, "50.00"),
                    (3, "2026-11-01", "S2", "P1", 3, "17.75"),
                ],
                "inventory": [
                    ("2026-10-31", "S1", "P1", 100, 10),
                    ("2026-10-31", "S2", "P1", 80, 10),
                    ("2026-11-01", "S1", "P1", 8, 10),
                    ("2026-11-01", "S1", "P2", 0, 5),
                    ("2026-11-01", "S2", "P1", 10, 10),
                ],
            }
            batch = write_batch(directory / "2026-11-01-initial", **rows)
            result = load_batch(batch)
            assert result["summary"]["reconciliation"] == {
                "sales_rows": 3, "net_sales": "78.00", "inventory_rows": 5,
                "stock_across_source_rows": 198,
            }
            with TestClient(app) as client:
                assert client.get("/healthz").json() == {"status": "ready"}
                yield client, directory, batch, rows
        finally:
            with owner, owner.cursor() as cursor:
                cursor.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(created))


def login(client, username="manager"):
    response = client.post("/api/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response


def test_sales_slice_dice_roll_up_and_pivot(warehouse):
    client, *_ = warehouse
    login(client)
    overview = client.get("/api/sales", params=FILTERS)
    assert overview.status_code == 200, overview.text
    assert overview.json()["totals"]["net_sales"] == 78
    assert overview.json()["totals"]["units_sold"] == 6
    assert overview.json()["trend"] == [
        {"period": "2026-10", "net_sales": 10.25, "units_sold": 2, "sales_lines": 1},
        {"period": "2026-11", "net_sales": 67.75, "units_sold": 4, "sales_lines": 2},
    ]

    cells = client.get("/api/cube", params={**FILTERS, "rows": "month", "columns": "region"}).json()["cells"]
    assert {(cell["row_key"], cell["column_key"]): cell["value"] for cell in cells} == {
        ("2026-10", "East"): 10.25, ("2026-11", "East"): 50, ("2026-11", "West"): 17.75,
    }
    transposed = client.get("/api/cube", params={**FILTERS, "rows": "region", "columns": "month"}).json()["cells"]
    assert {(c["row_key"], c["column_key"], c["value"]) for c in cells} == {
        (c["column_key"], c["row_key"], c["value"]) for c in transposed
    }
    drilled = client.get("/api/cube", params={
        **FILTERS, "rows": "store", "region": "East", "category": "Lighting",
    }).json()["cells"]
    assert drilled == [{"row_key": "S1", "row_label": "Ottawa", "value": 10.25}]
    selected = client.get("/api/cube", params={
        **FILTERS, "rows": "year", "region": ["East", "West"], "category": "Lighting",
    }).json()["cells"]
    assert selected == [{"row_key": "2026", "row_label": "2026", "value": 28.0}]
    assert client.get("/api/cube", params={**FILTERS, "rows": "month", "columns": "month"}).status_code == 422
    assert client.get("/api/sales", params={"start": FILTERS["end"], "end": FILTERS["start"]}).status_code == 422


def test_inventory_uses_single_snapshot_and_strict_threshold(warehouse):
    client, *_ = warehouse
    login(client)
    data = client.get("/api/inventory", params=FILTERS).json()
    assert data["totals"] == {
        "snapshot_date": "2026-11-01", "stock": 18, "below_reorder": 2, "out_of_stock": 1, "positions": 3,
    }
    assert [row["product_name"] for row in data["exceptions"]] == ["Chair", "Lamp"]
    old = client.get("/api/inventory", params={**FILTERS, "end": "2026-10-31"}).json()
    assert old["totals"]["stock"] == 180
    cube = client.get("/api/cube", params={
        **FILTERS, "fact": "inventory", "metric": "stock", "rows": "category", "columns": "region",
    }).json()
    assert cube["snapshot_date"] == "2026-11-01"
    assert sum(cell["value"] for cell in cube["cells"]) == 18
    assert client.get("/api/cube", params={
        **FILTERS, "fact": "inventory", "metric": "stock", "rows": "month",
    }).status_code == 422


def test_roles_and_session_revocation(warehouse):
    client, *_ = warehouse
    client.cookies.clear()
    assert client.get("/api/sales", params=FILTERS).status_code == 401
    login(client)
    assert client.get("/api/admin/runs").status_code == 403
    assert client.post("/api/admin/users", json={"username": "new", "password": PASSWORD}).status_code == 403
    login(client, "admin")
    assert client.get("/api/admin/runs").status_code == 200
    assert client.put("/api/admin/users/admin", json={"role": "manager", "enabled": True}).status_code == 409
    member, administrator = TestClient(app), TestClient(app)
    try:
        login(administrator, "admin")
        assert administrator.post("/api/admin/users", json={
            "username": "store.manager", "password": PASSWORD,
        }).status_code == 201
        login(member, "store.manager")
        assert member.get("/api/me").json()["role"] == "manager"
        assert administrator.put("/api/admin/users/store.manager", json={
            "role": "manager", "enabled": False,
        }).status_code == 200
        assert member.get("/api/me").status_code == 401
        assert administrator.post("/api/logout").status_code == 204
        assert administrator.get("/api/me").status_code == 401
    finally:
        member.close()
        administrator.close()


def test_batch_replay_rejects_and_failed_run_recovery(warehouse):
    _, directory, initial, rows = warehouse
    assert load_batch(initial)["already_loaded"] is True
    duplicate = write_batch(directory / "2026-11-02-replay", **rows)
    assert load_batch(duplicate)["summary"]["reconciliation"]["sales_rows"] == 3

    corrections = write_batch(directory / "2026-11-03-corrections",
        sales=[
            (2, "2026-11-01", "S1", "P2", 1, "51.00"),
            (4, "2026-11-02", "S1", "unknown", 1, "4.00"),
            (5, "2026-11-02", "S1", "P1", 1, "9.999"),
        ],
        inventory=[
            ("2026-11-02", "S1", "P1", 4, 10),
            ("2026-11-02", "S1", "P1", 3, 10),
            ("2026-11-02", "S1", "P2", 12, 6),
        ],
    )
    loaded = load_batch(corrections)
    assert loaded["status"] == "loaded_with_rejects"
    assert loaded["summary"]["rejected"] == 4

    recovery = write_batch(directory / "2026-11-04-broken",
                           sales=[(6, "2026-11-03", "S1", "P1", 1, "3.50")])
    inventory = recovery / "inventory.csv"
    valid_csv = inventory.read_text()
    inventory.write_text("wrong,header\n")
    with pytest.raises(ValueError, match="headers"):
        load_batch(recovery)
    inventory.write_text(valid_csv)
    assert load_batch(recovery)["status"] == "loaded"

    with closing(connect()) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*), SUM(net_sales_amount) FROM fact_sales")
        assert cursor.fetchone() == (4, Decimal("82.50"))
        cursor.execute("SELECT COUNT(*) FROM fact_inventory_snapshot")
        assert cursor.fetchone()[0] == 6
        cursor.execute("SELECT reason FROM etl_reject ORDER BY source_file, line_number")
        assert [row[0] for row in cursor].count("duplicate key in batch") == 2
        cursor.execute("SELECT status FROM etl_run WHERE batch_id = %s ORDER BY run_id", (recovery.name,))
        assert cursor.fetchall() == [("failed",), ("loaded",)]
