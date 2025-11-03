# api/intents.py — Deterministic NL → safe, dictionary-only SQL

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict
import re

@dataclass
class Plan:
    answer: str
    sql: str
    params: Dict[str, Any]

# Heuristic intent patterns
KW_MAP = {
    "list": r"(?:^|\b)(list|show|find|search)\b.*\btables?\b|tables?\b.*\b(list|show)\b",
    "describe": r"(?:^|\b)(describe|desc|columns?|structure|schema of)\b",
    "keys": r"(?:^|\b)(keys?|primary key|foreign key|constraints?)\b",
    "partitions": r"(?:^|\b)(partition|subpartition|interval|partitioning)\b",
}

# Safe Oracle identifier check (OWNER/TABLE/COLUMN)
SAFE_IDENT = re.compile(r"^[A-Z0-9_#$]+$")

def sanitize_ident(name: str) -> str:
    """
    Uppercase & validate an Oracle identifier (OWNER/TABLE).
    Only allows A–Z, 0–9, underscore, #, $; rejects quoted/unsafe names.
    """
    name = (name or "").strip().upper()
    if not name or not SAFE_IDENT.match(name):
        raise ValueError("Unsafe identifier")
    return name

def _extract_table(q: str) -> str | None:
    # Look for “… table <NAME>” or trailing token
    m = re.search(r"(?:table|of)\s+([a-zA-Z0-9_#$]+)", q)
    if not m:
        m = re.search(r"([a-zA-Z0-9_#$]+)\s*$", q)
    return m.group(1) if m else None

def plan_query(question: str, schema: str) -> Plan:
    """
    Map a natural-language question to a single, parameterized SQL statement
    against Oracle dictionary views. Never queries business data.
    """
    if not question or not schema:
        raise ValueError("question and schema are required")

    q = question.strip().lower()
    owner = sanitize_ident(schema)

    # --- Describe columns ---
    if re.search(KW_MAP["describe"], q):
        table = _extract_table(q)
        if not table:
            raise ValueError("Please specify a table name, e.g., 'describe table STG_PARTY_MASTER'.")
        table = sanitize_ident(table)
        sql = (
            "SELECT owner, table_name, column_id, column_name, data_type, data_length, "
            "       nullable, data_default "
            "FROM all_tab_columns "
            "WHERE owner = :owner AND table_name = :table "
            "ORDER BY column_id"
        )
        return Plan(answer=f"Columns of {table}", sql=sql, params={"owner": owner, "table": table})

    # --- Keys & constraints ---
    if re.search(KW_MAP["keys"], q):
        table = _extract_table(q)
        if not table:
            raise ValueError("Please specify a table name, e.g., 'keys of table TXN_ALERTS'.")
        table = sanitize_ident(table)
        sql = (
            "SELECT ac.constraint_name, ac.constraint_type, acc.table_name, acc.column_name, ac.r_constraint_name "
            "FROM all_constraints ac "
            "JOIN all_cons_columns acc "
            "  ON ac.owner = acc.owner AND ac.constraint_name = acc.constraint_name "
            "WHERE ac.owner = :owner AND ac.table_name = :table "
            "  AND ac.constraint_type IN ('P','U','R') "
            "ORDER BY ac.constraint_type, acc.position"
        )
        return Plan(answer=f"Keys & constraints for {table}", sql=sql, params={"owner": owner, "table": table})

    # --- Partitions ---
    if re.search(KW_MAP["partitions"], q):
        table = _extract_table(q)
        if not table:
            raise ValueError("Please specify a table name, e.g., 'partition info of table ALERT_HISTORY'.")
        table = sanitize_ident(table)
        sql = (
            "SELECT p.table_name, p.partition_name, p.high_value, p.tablespace_name, p.num_rows "
            "FROM all_tab_partitions p "
            "WHERE p.table_owner = :owner AND p.table_name = :table "
            "ORDER BY partition_position"
        )
        return Plan(answer=f"Partition info for {table}", sql=sql, params={"owner": owner, "table": table})

    # --- Default: list/search tables by keyword derived from text ---
    kw = "%" + re.sub(r"[^a-z0-9_]+", "%", q) + "%"
    sql = (
        "SELECT owner, table_name, comments "
        "FROM all_tab_comments "
        "WHERE owner = :owner "
        "  AND (LOWER(table_name) LIKE LOWER(:kw) OR LOWER(comments) LIKE LOWER(:kw2)) "
        "ORDER BY table_name"
    )
    return Plan(
        answer=f"Tables in {owner} matching your query.",
        sql=sql,
        params={"owner": owner, "kw": kw, "kw2": kw},
    )

