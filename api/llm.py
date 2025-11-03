# api/llm.py — Provider-agnostic LLM wrapper using LiteLLM
# pip install litellm
# Env:
#   LLM_MODEL=gpt-4o-mini            # or azure/<deployment>, anthropic/claude-3-haiku, google/gemini-1.5-flash, ollama/llama3, etc.
#   OPENAI_API_KEY=...               # or provider-specific key per LiteLLM docs
#   LLM_MAX_TOKENS=512
#   LLM_TEMPERATURE=0.2

from __future__ import annotations

import os
from typing import List, Dict, Any

try:
    from litellm import completion
except Exception as e:  # pragma: no cover
    raise RuntimeError(
        "litellm is required for api/llm.py. Install with `pip install litellm`."
    ) from e

SYSTEM_PROMPT = (
    "You are OFSAA-BOT, an assistant that explains Oracle METADATA only. "
    "You NEVER invent or execute SQL. You summarize results that tools provide: tables, columns, keys, partitions, "
    "and relationships derived from dictionary views. Be concise, audit-friendly, and avoid speculation. "
    "If asked for business data, politely refuse and clarify that you have access to dictionary metadata only. "
    "Prefer one clear paragraph followed by short bullet points when listing items."
)

MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "512"))
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))


def _stringify_context(
    question: str,
    schema: str,
    tables: List[Dict[str, Any]] | None,
    sql_snippets: List[str] | None,
    relations: List[Dict[str, Any]] | None,
) -> str:
    lines: List[str] = []
    lines.append(f"Question: {question}")
    lines.append(f"Schema: {schema}")

    if tables:
        lines.append("Tables (top 10):")
        for t in tables[:10]:
            owner = t.get("OWNER", schema)
            name = t.get("TABLE_NAME") or t.get("TABLE") or "?"
            comments = t.get("COMMENTS") or "-"
            lines.append(f"- {owner}.{name}: {comments}")

    if relations:
        lines.append("Relations (edges):")
        for e in relations[:20]:
            src = e.get("src_table")
            dst = e.get("dst_table")
            sc = e.get("src_cols")
            dc = e.get("dst_cols")
            cn = e.get("constraint_name")
            lines.append(f"- {src} ({sc}) -> {dst} ({dc}) via {cn}")

    if sql_snippets:
        lines.append("SQL used (for audit):")
        for s in sql_snippets[:3]:
            s = (s or "").strip()
            lines.append("---")
            lines.append(s)
            lines.append("---")

    # Guidance for the model about style & constraints
    lines.append(
        "Instructions: Explain in plain English. Do not invent tables or columns. "
        "Use short, direct sentences. If nothing is found, suggest narrower keywords or confirm schema. "
        "If asked for business data content, refuse politely."
    )
    return "\n".join(lines)


def generate_reply(
    question: str,
    schema: str,
    tables: List[Dict[str, Any]] | None = None,
    sql_snippets: List[str] | None = None,
    relations: List[Dict[str, Any]] | None = None,
    tone: str = "friendly",  # "friendly" | "formal"
) -> str:
    """
    Produce a natural reply using an LLM. The model only sees tool outputs and audit SQL.
    Safety: We never execute or generate SQL here; DB access stays in tools.
    """
    style = "Use a warm, professional tone." if tone == "friendly" else "Use a formal, concise tone."
    user_ctx = _stringify_context(question, schema, tables, sql_snippets, relations)

    resp = completion(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT + " " + style},
            {"role": "user", "content": user_ctx},
        ],
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
    )
    # LiteLLM returns OpenAI-style objects
    return resp.choices[0].message.get("content", "").strip()
