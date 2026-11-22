import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated, Literal

import psycopg2
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import analytics, auth
from .db import ROOT, Database

ROLES = Literal["manager", "admin"]
USERNAME = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{2,39}$")]
PASSWORD = Annotated[str, Field(min_length=12, max_length=128)]
DUMMY_HASH = auth.password_hash("anonymous timing sample")
LOGGER = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app):
    app.state.db = Database()
    try:
        yield
    finally:
        app.state.db.close()


app = FastAPI(title="Group 14 Retail Analytics", lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount("/assets", StaticFiles(directory=ROOT / "web"), name="assets")


@app.middleware("http")
async def response_headers(request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(psycopg2.Error)
async def database_error(request, exc):
    LOGGER.error("Warehouse query failed on %s (%s)", request.url.path, exc.pgcode or type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "The warehouse is temporarily unavailable."})


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    return JSONResponse(status_code=422, content={
        "detail": [{"loc": error["loc"], "msg": error["msg"]} for error in exc.errors()],
    })


def database(request: Request):
    return request.app.state.db


DB = Annotated[Database, Depends(database)]


def current_user(request: Request, db: DB):
    with db.cursor(read_only=True) as cursor:
        user = auth.find_user(cursor, request.cookies.get(auth.COOKIE))
    if not user:
        raise HTTPException(401, "Sign in to continue.")
    return user


User = Annotated[dict, Depends(current_user)]


def admin_user(user: User):
    if user["role"] != "admin":
        raise HTTPException(403, "Administrator access is required.")
    return user


Admin = Annotated[dict, Depends(admin_user)]


def lock_admin_write(cursor, username):
    cursor.execute("SELECT pg_advisory_xact_lock(%s)", (auth.ROLE_LOCK,))
    cursor.execute("SELECT 1 FROM app_user WHERE username = %s AND role = 'admin' AND enabled", (username,))
    if cursor.fetchone() is None:
        raise HTTPException(403, "Administrator access is required.")


class Login(BaseModel):
    username: USERNAME
    password: str = Field(min_length=1, max_length=128)


class NewUser(BaseModel):
    username: USERNAME
    password: PASSWORD
    role: ROLES = "manager"


class UserUpdate(BaseModel):
    role: ROLES
    enabled: bool
    password: PASSWORD | None = None


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "web/index.html", headers={"Cache-Control": "no-cache"})


@app.get("/healthz", include_in_schema=False)
def health(db: DB):
    with db.cursor(read_only=True) as cursor:
        cursor.execute("SELECT 1 FROM dim_date LIMIT 1")
    return {"status": "ready"}


@app.post("/api/login")
def login(body: Login, response: Response, db: DB):
    with db.cursor(read_only=True) as cursor:
        cursor.execute("SELECT password_hash, role, enabled FROM app_user WHERE username = %s", (body.username,))
        account = cursor.fetchone()
    stored = account["password_hash"] if account else DUMMY_HASH
    if not auth.verify_password(body.password, stored) or not account or not account["enabled"]:
        raise HTTPException(401, "Username or password is incorrect.")

    with db.cursor() as cursor:
        cursor.execute("SELECT role, password_hash, enabled FROM app_user WHERE username = %s FOR SHARE", (body.username,))
        current = cursor.fetchone()
        if not current or not current["enabled"] or current["password_hash"] != stored:
            raise HTTPException(401, "Username or password is incorrect.")
        token = auth.create_session(cursor, body.username)
    response.set_cookie(
        auth.COOKIE, token, max_age=auth.SESSION_SECONDS, httponly=True,
        secure=os.environ.get("OLAP_COOKIE_SECURE", "false").lower() == "true", samesite="strict",
    )
    return {"username": body.username, "role": current["role"]}


@app.post("/api/logout", status_code=204)
def logout(request: Request, response: Response, db: DB):
    token = request.cookies.get(auth.COOKIE)
    if token:
        with db.cursor() as cursor:
            cursor.execute("DELETE FROM app_session WHERE token_hash = %s", (auth.token_digest(token),))
    response.delete_cookie(
        auth.COOKIE, httponly=True, samesite="strict",
        secure=os.environ.get("OLAP_COOKIE_SECURE", "false").lower() == "true",
    )


@app.get("/api/me")
def whoami(user: User):
    return user


@app.get("/api/metadata")
def metadata(db: DB, user: User):
    with db.cursor(read_only=True) as cursor:
        return {**analytics.metadata(cursor), "demo": os.environ.get("OLAP_DEMO", "false").lower() == "true"}


@app.get("/api/sales")
def sales(filters: Annotated[analytics.Filters, Query()], db: DB, user: User):
    with db.cursor(read_only=True) as cursor:
        return analytics.sales_dashboard(cursor, filters)


@app.get("/api/inventory")
def inventory(filters: Annotated[analytics.Filters, Query()], db: DB, user: User):
    with db.cursor(read_only=True) as cursor:
        return analytics.inventory_dashboard(cursor, filters)


@app.get("/api/cube")
def cube(filters: Annotated[analytics.CubeRequest, Query()], db: DB, user: User):
    with db.cursor(read_only=True) as cursor:
        try:
            return analytics.cube(cursor, filters)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc


@app.get("/api/admin/runs")
def runs(db: DB, user: Admin):
    with db.cursor(read_only=True) as cursor:
        cursor.execute("""
            SELECT run_id, batch_id, started_at, finished_at, status, summary, error
            FROM etl_run ORDER BY run_id DESC LIMIT 30
        """)
        return cursor.fetchall()


@app.get("/api/admin/users")
def users(db: DB, user: Admin):
    with db.cursor(read_only=True) as cursor:
        cursor.execute("SELECT username, role, enabled FROM app_user ORDER BY username")
        return cursor.fetchall()


@app.post("/api/admin/users", status_code=201)
def add_user(body: NewUser, db: DB, user: Admin):
    hashed = auth.password_hash(body.password)
    with db.cursor() as cursor:
        lock_admin_write(cursor, user["username"])
        cursor.execute("""
            INSERT INTO app_user (username, password_hash, role) VALUES (%s, %s, %s)
            ON CONFLICT (username) DO NOTHING RETURNING username, role, enabled
        """, (body.username, hashed, body.role))
        created = cursor.fetchone()
        if not created:
            raise HTTPException(409, "That username already exists.")
        return created


@app.put("/api/admin/users/{username}")
def update_user(username: str, body: UserUpdate, db: DB, user: Admin):
    if username == user["username"] and (body.role != "admin" or not body.enabled):
        raise HTTPException(409, "Your account must keep administrator access.")
    hashed = auth.password_hash(body.password) if body.password else None
    with db.cursor() as cursor:
        lock_admin_write(cursor, user["username"])
        cursor.execute("""
            UPDATE app_user SET role = %s, enabled = %s, password_hash = COALESCE(%s, password_hash)
            WHERE username = %s RETURNING username, role, enabled
        """, (body.role, body.enabled, hashed, username))
        updated = cursor.fetchone()
        if not updated:
            raise HTTPException(404, "Account not found.")
        if not body.enabled or hashed:
            cursor.execute("DELETE FROM app_session WHERE username = %s", (username,))
        return updated
