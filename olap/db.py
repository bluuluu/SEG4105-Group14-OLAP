import os
from contextlib import contextmanager
from pathlib import Path
from threading import BoundedSemaphore

import psycopg2
from psycopg2 import pool, sql
from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE_TABLES = (
    "dim_date", "dim_product", "dim_store", "fact_sales", "fact_inventory_snapshot",
)
SESSION_TABLES = ("app_user", "app_session")
ETL_TABLES = ("etl_run", "etl_reject")


def url(variable="DATABASE_URL"):
    return os.environ.get(variable) or os.environ.get("DATABASE_URL", "postgresql:///olap")


def connect(variable="DATABASE_URL"):
    return psycopg2.connect(url(variable), connect_timeout=5)


class Database:
    def __init__(self):
        self.capacity = BoundedSemaphore(16)
        self.pool = pool.ThreadedConnectionPool(2, 16, url(), connect_timeout=5)

    @contextmanager
    def cursor(self, *, read_only=False):
        with self.capacity:
            conn = self.pool.getconn()
            try:
                with conn, conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    if read_only:
                        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    cursor.execute("SET LOCAL statement_timeout = '8s'")
                    yield cursor
            finally:
                self.pool.putconn(conn, close=bool(conn.closed))

    def close(self):
        self.pool.closeall()


def initialize(conn):
    with conn, conn.cursor() as cursor:
        cursor.execute((ROOT / "sql/schema.sql").read_text())
        for role, env in (("olap_web", "OLAP_WEB_DB_PASSWORD"), ("olap_etl", "OLAP_ETL_DB_PASSWORD")):
            password = os.environ.get(env)
            if not password:
                continue
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
            verb = "ALTER" if cursor.fetchone() else "CREATE"
            cursor.execute(
                sql.SQL("{} ROLE {} LOGIN PASSWORD %s").format(sql.SQL(verb), sql.Identifier(role)),
                (password,),
            )
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
            if role == "olap_web":
                grant(cursor, role, "SELECT", (*WAREHOUSE_TABLES, "etl_run"))
                grant(cursor, role, "SELECT, INSERT, UPDATE", ("app_user",))
                grant(cursor, role, "SELECT, INSERT, DELETE", ("app_session",))
            else:
                grant(cursor, role, "SELECT, INSERT, UPDATE", (*WAREHOUSE_TABLES, *ETL_TABLES))
                cursor.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO olap_etl")


def grant(cursor, role, permissions, tables):
    cursor.execute(sql.SQL("GRANT {} ON {} TO {}").format(
        sql.SQL(permissions),
        sql.SQL(", ").join(map(sql.Identifier, tables)),
        sql.Identifier(role),
    ))
