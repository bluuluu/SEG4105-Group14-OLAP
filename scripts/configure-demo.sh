#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
umask 077
python3 - <<'PY'
from pathlib import Path
from secrets import token_urlsafe

try:
    with Path(".env").open("x") as stream:
        for role in ("OWNER", "WEB", "ETL"):
            stream.write(f"OLAP_{role}_DB_PASSWORD={token_urlsafe(24)}\n")
        for role in ("ADMIN", "MANAGER"):
            stream.write(f"OLAP_BOOTSTRAP_{role}_PASSWORD={token_urlsafe(18)}\n")
        stream.write("OLAP_DEMO=true\nOLAP_PORT=8014\n")
except FileExistsError:
    print("Using the existing .env configuration.")
PY
mkdir -p data/inbox
chmod 755 data data/inbox
