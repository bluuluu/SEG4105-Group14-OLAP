# Software Components

The platform loads retail extracts into a PostgreSQL warehouse and lets managers explore sales and inventory through a web dashboard. This inventory describes the current source files.

## 1. Component Inventory

Paths are relative to the repository root.

| Component | Directory or file path | Primary responsibility | Key dependencies |
| --- | --- | --- | --- |
| Web application controller | [`web/app.js`](../web/app.js) | Manage sign-in, filters, page navigation, drill-down, roll-up, pivot requests, and account actions. | Browser Fetch API, `views.js`, `charts.js`, `ui.js`, backend JSON endpoints |
| Dashboard views | [`web/views.js`](../web/views.js) | Build overview, inventory, pivot, and administration views. Define the available axes and navigation hierarchies. | `ui.js`, results returned by the API |
| Charts and UI helpers | [`web/charts.js`](../web/charts.js), [`web/ui.js`](../web/ui.js) | Draw the sales chart, format dates and CAD amounts, and escape displayed text. | Browser Canvas and DOM APIs |
| Page and styling | [`web/index.html`](../web/index.html), [`web/styles.css`](../web/styles.css) | Provide the page structure and dashboard appearance. | JavaScript modules under `web/` |
| HTTP application | [`olap/app.py`](../olap/app.py) | Serve the dashboard and API, validate requests, check account roles, and handle database errors. | FastAPI, Pydantic, Uvicorn, database, authentication, analytics |
| Authentication | [`olap/auth.py`](../olap/auth.py) | Hash passwords, create sessions, and resolve enabled accounts. Sessions expire after eight hours. | Python `hashlib`, `hmac`, and `secrets`; PostgreSQL account and session tables |
| OLAP queries | [`olap/analytics.py`](../olap/analytics.py) | Apply filters, aggregate sales, select inventory snapshots, and calculate pivots and refresh information. | Pydantic, SQL joins, shared dimensions and fact tables |
| Database access | [`olap/db.py`](../olap/db.py) | Manage connections, transactions, initialization, and runtime database grants. | Psycopg 2, PostgreSQL, `sql/schema.sql` |
| ETL loader | [`olap/etl.py`](../olap/etl.py) | Validate CSV records, resolve dimension keys, stage and upsert facts, reconcile totals, quarantine rejected rows, and retry transient failures. | Python CSV and Decimal libraries, Psycopg 2, warehouse and ETL audit tables |
| Command-line interface and worker | [`olap/__main__.py`](../olap/__main__.py) | Provide `init`, `load`, `user`, and `worker` commands. Poll completed batches in order. | `argparse`, ETL, authentication, database initialization, demo generator |
| Demo generator | [`olap/demo.py`](../olap/demo.py) | Generate synthetic sales, inventory, product, and store extracts for the demo. | Python standard library, CSV batch format |
| Warehouse schema | [`sql/schema.sql`](../sql/schema.sql), [`sql/example_queries.sql`](../sql/example_queries.sql) | Define dimensions, facts, account/session tables, audit tables, constraints, indexes, and example analysis queries. | PostgreSQL 16 |
| Container setup | [`Dockerfile`](../Dockerfile), [`compose.yaml`](../compose.yaml) | Build the Python image and run the database, bootstrap, app, and worker services. | Python 3.12 image, PostgreSQL 16 image, Docker Compose, `.env` configuration |
| Demo configuration | [`scripts/configure-demo.sh`](../scripts/configure-demo.sh) | Generate local credentials and create the extract inbox. | Shell, Python 3, local filesystem |
| Verification | [`tests/test_warehouse.py`](../tests/test_warehouse.py), [`scripts/benchmark.py`](../scripts/benchmark.py) | Test warehouse/API behavior and measure requests from concurrent authenticated sessions. | Pytest, HTTPX, FastAPI TestClient, PostgreSQL; running app for the benchmark |
| Schedule analysis | [`scripts/OLAP_Schedule_Monte_Carlo.py`](../scripts/OLAP_Schedule_Monte_Carlo.py) | Simulate uncertainty in the project schedule. | NumPy and Matplotlib, installed separately |

Runtime package versions are listed in [`requirements.txt`](../requirements.txt). Test and simulation packages are installed separately as described in the [methodology](METHODOLOGY.md).

## 2. External Interfaces and APIs

### Input interfaces

- The browser sends JSON credentials to `POST /api/login`. Authenticated requests use the `olap_session` cookie.
- `GET /api/sales` and `GET /api/inventory` accept a required `start` and `end` date, with optional repeated `region`, `store`, `category`, and `product` filters.
- `GET /api/cube` accepts those filters plus `fact`, `metric`, `rows`, and optional `columns`. The server checks the allowed dimensions and measures.
- Administrators use `GET /api/admin/runs`, `GET /api/admin/users`, `POST /api/admin/users`, and `PUT /api/admin/users/{username}`.
- A completed batch under `data/inbox/<batch-id>/` contains `products.csv`, `stores.csv`, `sales.csv`, `inventory.csv`, and an empty `READY` marker. Exact CSV headers are listed in the [README](../README.md#daily-extracts-and-reconciliation).
- Local operators use `python -m olap init`, `load <directory>`, `user <username>`, and `worker`.

### Output interfaces

- The API returns JSON for sales, inventory, pivot cells, account state, and authorized administration records. The web modules turn these results into charts and tables.
- `GET /api/metadata` returns filter choices and refresh information. `GET /api/me` returns the signed-in account. `POST /api/logout` removes the current session.
- `GET /healthz` checks database access and returns `{"status":"ready"}` when successful.
- ETL writes accepted dimensions and facts, records batch results in `etl_run`, and stores rejected-row details in `etl_reject`.
- The worker writes processing and error messages to its logs. The benchmark prints successful request counts and p95/maximum response times and returns a failing exit status when its criteria are not met.
