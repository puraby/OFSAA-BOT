# api/response_nlg.py — Simple natural language generator (fallback if LLM unavailable)

from __future__ import annotations
from typing import List, Dict, Any

def humanize_count(n: int) -> str:
    return f"{n} row{'s' if n != 1 else ''}"

def _summarize_rows(rows: List[Dict[str, Any]], max_items: int = 5) -> str:
    if not rows:
        return "No matching rows."
    keys = rows[0].keys()
    has_owner = "OWNER" in keys
    has_table = "TABLE_NAME" in keys
    has_comments = "COMMENTS" in keys

    snippets = []
    for r in rows[:max_items]:
        if has_table and has_comments:
            snippets.append(f"• {r.get('TABLE_NAME')} — {r.get('COMMENTS')}")
        elif has_table:
            snippets.append(f"• {r.get('TABLE_NAME')}")
        else:
            # fallback: show first two columns
            cols = list(keys)
            val = ", ".join(str(r.get(c)) for c in cols[:2])
            snippets.append(f"• {val}")
    more = "" if len(rows) <= max_items else f"\n…and {len(rows) - max_items} more."
    return "\n".join(snippets) + more

def nlg_reply(title: str, rows: List[Dict[str, Any]] | None, owner: str, tone: str = "friendly") -> str:
    """
    Produce a short paragraph + bullets summarizing results.
    tone: "friendly" | "formal"
    """
    n = len(rows) if rows else 0
    lead = (
        f"{title}. I found {humanize_count(n)} in {owner}."
        if tone == "friendly"
        else f"{title}. Located {humanize_count(n)} in {owner}."
    )
    if not rows:
        return lead + " Try another keyword or verify the schema."

    bullets = _summarize_rows(rows)
    tail = "\n\nIf you like, I can narrow this down or switch to columns/keys/partitions."
    return f"{lead}\n\n{bullets}{tail}"

