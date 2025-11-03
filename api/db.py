# api/db.py — Oracle read-only connector + query helpers

from __future__ import annotations
from typing import Any, Dict, List

import os
import oracledb

# Env:
# ORA_DSN="HOST=localhost;PORT=1521;SERVICE_NAME=FREEPDB1"
# ORA_USER="scott"
# ORA_PASS="tiger"

_DSN = os.getenv("ORA_DSN", "HOST=localhost;PORT=1521;SERVICE_NAME=FREEPDB1")
_USER = os.getenv("ORA_USER")
_PASS = os.getenv("ORA_PASS")

# Thin mode (no instant client needed). If you use a wallet/TCPS, configure per oracledb docs.
oracledb.init_oracle_client(lib_dir=None)  # no-op for Thin mode


def _dsn_from_env(dsn_text: str) -> str:
    parts = dict(p.split("=", 1) for p in dsn_text.split(";") if "=" in p)
    host = parts.get("HOST", "localhost")
    port = int(parts.get("PORT", 1521))
    service = parts.get("SERVICE_NAME") or parts.get("SERVICE") or "FREEPDB1"
    return oracledb.makedsn(host, port, service_name=service)


def _connect():
    if not (_USER and _PASS):
        raise RuntimeError("ORA_USER/ORA_PASS not set (unset DEMO_MODE to require DB)")
    dsn = _dsn_from_env(_DSN)
    conn = oracledb.connect(user=_USER, password=_PASS, dsn=dsn)
    return conn


def run_query(sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Execute a parameterized, read-only query and return rows as dicts.
    Caller ensures the SQL targets dictionary views only.
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def healthcheck() -> str:
    """
    Returns 'demo' when DEMO_MODE is set, otherwise 'up'/'down' based on a trivial check.
    """
    try:
        if os.getenv("DEMO_MODE"):
            return "demo"
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute("select 1 from dual")
                _ = cur.fetchone()
            return "up"
        finally:
            conn.close()
    except Exception:
        return "down"

