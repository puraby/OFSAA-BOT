# api/chat_router.py — Conversational endpoint using ML + safe tools + LLM NLG
from __future__ import annotations

import os
import re
from typing import Dict, Any, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from intents import plan_query, sanitize_ident
from db import run_query
from ml_intents import predict_intent
from response_nlg import nlg_reply  # fallback if LLM not available
from llm import generate_reply

# Reuse SQL from explain module for relationship-style questions
from explain import SQL_FIND_TABLES, SQL_FK_EDGES, SQL_PK

router = APIRouter()


# -----------------------------
# Models
# -----------------------------
class ChatReq(BaseModel):
    message: str
    schema: str = "OFSAAFCCM"
    history: List[Dict[str, str]] = []  # optional; not used yet
    tone: str = "friendly"              # "friendly" | "formal"


class ChatResp(BaseModel):
    reply: str
    tables: Optional[List[Dict[str, Any]]] = None
    sql_snippets: Optional[List[str]] = None


# -----------------------------
# Route
# -----------------------------
@router.post("/chat", response_model=ChatResp)
def chat(req: ChatReq) -> ChatResp:
    """
    Natural, human-like chat endpoint:
    1) Try deterministic planner (regex → safe SQL).
    2) If not matched, use tiny ML intent classifier.
    3) For "explain connections" style prompts, build a relationship view.
    4) In all cases, craft the reply with LLM; fallback to template NLG if LLM fails.
    """
    text = (req.message or "").strip()
    if not text:
        return ChatResp(reply="Please type a question about tables, columns, keys, or partitions.")

    owner = sanitize_ident(req.schema)

    # 0) Detect "explain/how connected/related" for a few common families (alert/kyc/party/txn)
    if re.search(r"(explain|how.*connect|relation|related)", text, re.I) and re.search(
        r"(alert|kyc|party|txn)", text, re.I
    ):
        kw_match = re.search(r"(alert|kyc|party|txn)[a-z_]*", text, re.I)
        if kw_match:
            kw = kw_match.group(0).upper()
            rows, edges, pk_rows = _exec_explain(owner, kw)
            sqls = [SQL_FIND_TABLES, SQL_FK_EDGES, SQL_PK]
            # Ask LLM to narrate; if it fails, fall back to template
            try:
                reply = generate_reply(
                    question=text,
                    schema=owner,
                    tables=rows,
                    sql_snippets=sqls,
                    relations=[
                        {
                            "src_table": e["SRC_TABLE"],
                            "src_cols": e["SRC_COLS"],
                            "dst_table": e["DST_TABLE"],
                            "dst_cols": e["DST_COLS"],
                            "constraint_name": e["CONSTRAINT_NAME"],
                        }
                        for e in edges
                    ],
                    tone=req.tone,
                )
            except Exception:
                reply = nlg_reply(f"{kw} tables in {owner}", rows, owner, tone=req.tone)
            return ChatResp(reply=reply, tables=rows, sql_snippets=sqls)

    # 1) Deterministic planner → SQL → rows
    try:
        plan = plan_query(text, owner)
        rows = _exec_or_mock(plan.sql, plan.params, owner)
        sqls = [plan.sql]
        try:
            reply = generate_reply(text, owner, rows, sqls, tone=req.tone)
        except Exception:
            reply = nlg_reply(plan.answer, rows, owner, tone=req.tone)
        return ChatResp(reply=reply, tables=rows, sql_snippets=sqls)
    except Exception:
        pass  # fall through to ML intent

    # 2) ML intent fallback
    intent = predict_intent(text)
    sql, params, title = None, {}, ""

    if intent.label == "list":
        kw = "%" + re.sub(r"[^a-z0-9_]+", "%", text.lower()) + "%"
        sql = (
            "SELECT owner, table_name, comments "
            "FROM all_tab_comments "
            "WHERE owner = :owner "
            "AND (LOWER(table_name) LIKE LOWER(:kw) OR LOWER(comments) LIKE LOWER(:kw2)) "
            "ORDER BY table_name"
        )
        params = {"owner": owner, "kw": kw, "kw2": kw}
        title = f"Tables in {owner} matching your query"

    elif intent.label == "describe":
        m = re.search(r"([a-zA-Z0-9_#$]+)$", text)
        table = sanitize_ident(m.group(1)) if m else None
        if not table:
            return ChatResp(reply="Please specify a table name, e.g., 'describe table STG_PARTY_MASTER'.")
        sql = (
            "SELECT owner, table_name, column_id, column_name, data_type, data_length, nullable, data_default "
            "FROM all_tab_columns "
            "WHERE owner = :owner AND table_name = :table "
            "ORDER BY column_id"
        )
        params = {"owner": owner, "table": table}
        title = f"Columns of {table}"

    elif intent.label == "keys":
        m = re.search(r"([a-zA-Z0-9_#$]+)$", text)
        table = sanitize_ident(m.group(1)) if m else None
        if not table:
            return ChatResp(reply="Please specify a table name, e.g., 'keys of table TXN_ALERTS'.")
        sql = (
            "SELECT ac.constraint_name, ac.constraint_type, acc.table_name, acc.column_name, ac.r_constraint_name "
            "FROM all_constraints ac "
            "JOIN all_cons_columns acc ON ac.owner = acc.owner AND ac.constraint_name = acc.constraint_name "
            "WHERE ac.owner = :owner AND ac.table_name = :table "
            "AND ac.constraint_type IN ('P','U','R') "
            "ORDER BY ac.constraint_type, acc.position"
        )
        params = {"owner": owner, "table": table}
        title = f"Keys & constraints for {table}"

    elif intent.label == "partitions":
        m = re.search(r"([a-zA-Z0-9_#$]+)$", text)
        table = sanitize_ident(m.group(1)) if m else None
        if not table:
            return ChatResp(reply="Please specify a table name, e.g., 'partition info of table ALERT_HISTORY'.")
        sql = (
            "SELECT p.table_name, p.partition_name, p.high_value, p.tablespace_name, p.num_rows "
            "FROM all_tab_partitions p "
            "WHERE p.table_owner = :owner AND p.table_name = :table "
            "ORDER BY partition_position"
        )
        params = {"owner": owner, "table": table}
        title = f"Partition info for {table}"

    else:
        return ChatResp(
            reply=(
                "I can help with tables, columns, keys, partitions, and explain how related tables connect. "
                "Try: 'list tables for kyc', 'describe table STG_PARTY_MASTER', "
                "'keys of table TXN_ALERTS', or 'explain how ALERT tables are related'."
            )
        )

    rows = _exec_or_mock(sql, params, owner)
    sqls = [sql]
    try:
        reply = generate_reply(text, owner, rows, sqls, tone=req.tone)
    except Exception:
        reply = nlg_reply(title, rows, owner, tone=req.tone)
    return ChatResp(reply=reply, tables=rows, sql_snippets=sqls)


# -----------------------------
# Helpers
# -----------------------------
def _exec_or_mock(sql: str, params: Dict[str, Any], owner: str) -> List[Dict[str, Any]]:
    if os.getenv("DEMO_MODE"):
        return [
            {"OWNER": owner, "TABLE_NAME": "TXN_ALERTS", "COMMENTS": "Alerts generated by batch (daily)"},
            {"OWNER": owner, "TABLE_NAME": "ALERT_HISTORY", "COMMENTS": "Alert timeline and status transitions"},
            {"OWNER": owner, "TABLE_NAME": "STG_PARTY_MASTER", "COMMENTS": "Staging for party/customer info"},
        ]
    return run_query(sql, params)


def _exec_explain(owner: str, kw: str):
    """Fetch tables + FK edges + PK columns for a given keyword (dictionary-only)."""
    if os.getenv("DEMO_MODE"):
        rows = [
            {"OWNER": owner, "TABLE_NAME": "TXN_ALERTS", "COMMENTS": "Alerts generated by batch (daily)"},
            {"OWNER": owner, "TABLE_NAME": "ALERT_HISTORY", "COMMENTS": "Alert timeline and status transitions"},
            {"OWNER": owner, "TABLE_NAME": "STG_PARTY_MASTER", "COMMENTS": "Staging for party/customer info"},
        ]
        edges = [
            {
                "CONSTRAINT_NAME": "FK_ALERTS_PARTY",
                "SRC_TABLE": "TXN_ALERTS",
                "SRC_COLS": "PARTY_ID",
                "DST_TABLE": "STG_PARTY_MASTER",
                "DST_COLS": "PARTY_ID",
            },
            {
                "CONSTRAINT_NAME": "FK_HISTORY_ALERTS",
                "SRC_TABLE": "ALERT_HISTORY",
                "SRC_COLS": "ALERT_ID",
                "DST_TABLE": "TXN_ALERTS",
                "DST_COLS": "ALERT_ID",
            },
        ]
        pk_rows = [
            {"TABLE_NAME": "TXN_ALERTS", "PK_COLS": "ALERT_ID"},
            {"TABLE_NAME": "ALERT_HISTORY", "PK_COLS": "HIST_ID"},
            {"TABLE_NAME": "STG_PARTY_MASTER", "PK_COLS": "PARTY_ID"},
        ]
        return rows, edges, pk_rows

    rows = run_query(SQL_FIND_TABLES, {"owner": owner, "kw": f"%{kw}%"})
    edges = run_query(SQL_FK_EDGES, {"owner": owner, "kw": f"%{kw}%"})
    pk_rows = run_query(SQL_PK, {"owner": owner, "kw": f"%{kw}%"})
    return rows, edges, pk_rows

