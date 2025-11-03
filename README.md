# OFSAA-BOT
A safe, read-only AI assistant that answers natural-language questions about your Oracle schema’s metadata (tables, columns, keys, partitions) and can explain how related tables connect—in human language. It never queries business data, only Oracle dictionary views.

2) High-level architecture
Streamlit UI (ui/app.py)
   │   user chat, quick prompts, tone selector
   ▼
FastAPI (api/app.py)
   ├─ /ask       – deterministic NL→SQL (no LLM)
   ├─ /chat      – natural chat replies (Planner/ML → Tools → LLM NLG)
   └─ /explain   – find keyword tables + FK/PK graph → human summary

Core API modules:
   ├─ intents.py        – deterministic NL→SQL planner (safe, dictionary-only)
   ├─ db.py             – Oracle connector (read-only, parameterized)
   ├─ ml_intents.py     – tiny TF-IDF + LinearSVC intent classifier
   ├─ response_nlg.py   – template NLG fallback (friendly/formal)
   ├─ explain.py        – table discovery + FK edges + PK columns
   └─ llm.py            – provider-agnostic LLM wrapper (LiteLLM)


Key principle: All database access goes through parameterized, read-only SQL targeting Oracle dictionary views (ALL_TAB_COMMENTS, ALL_TAB_COLUMNS, ALL_CONSTRAINTS, ALL_CONS_COLUMNS, ALL_TAB_PARTITIONS).
Never business data tables.

3) User flow (step by step)
A) Normal chat (UI → /chat)

User types: “columns of STG_PARTY_MASTER” or “show alert tables”.

FastAPI /chat receives {message, schema, tone}.

Planner (deterministic): intents.plan_query() tries to map the message to one safe SQL (describe/keys/partitions/list).

If it succeeds → run the SQL → fetch rows.

If it doesn’t → fall back to ML intent classifier (below).

ML fallback (tiny classifier): If the planner didn’t match, ml_intents.predict_intent() classifies the intent among list/describe/keys/partitions/other, and builds a safe SQL accordingly.

Query execution: db.run_query() executes the parameterized statement (or returns mock rows in DEMO_MODE=1).

Natural reply: llm.generate_reply() turns the tool output into a human-like answer (tone: friendly/formal). If the LLM is unavailable, response_nlg.nlg_reply() produces a clear, template-based fallback.

UI renders: the natural text + Results (dataframe), SQL Used (for audit), Notes.

B) “Explain how tables connect” (UI → /explain button, or ask in /chat)

User asks: “what are the alert tables and how are they connected?”

/chat detects a relationship-style prompt (keywords like explain/related/connected + alert/kyc/party/txn), or the UI calls /explain directly.

explain.py:

Finds tables matching the keyword (name LIKE ‘%ALERT%’) from ALL_TAB_COMMENTS.

Collects foreign-key edges from ALL_CONSTRAINTS + ALL_CONS_COLUMNS.

Gets primary keys for those tables.

LLM narration: llm.generate_reply() turns the list of tables/edges into a plain-English summary (hubs, edges, glossary). If LLM fails, falls back to a template explanation in explain.py.

UI shows: narrative + table list + SQL Used. (Optional: you can add a graph view later.)

C) Deterministic mode (UI → /ask)

For audits/demos, /ask skips LLM and ML entirely: it’s regex → SQL only.

4) Safety & audit

Dictionary-only: Queries target ALL_* views; no business data is touched.

Parameterization: Every SQL uses bind variables (:owner, :table, :kw); inputs go through sanitize_ident() (uppercase + strict regex for OWNER/TABLE).

Allow-list: The UI requires a schema (e.g., OFSAAFCCM); the server validates it.

Audit trail: The API returns the exact SQL used, visible in the UI “SQL Used” tab.

LLM boundary: The LLM never runs SQL. It only summarizes tool outputs and the SQL string (for narration, not execution).

Demo mode: DEMO_MODE=1 replaces DB calls with deterministic mocks—great for demos without DB credentials.

5) ML features (what’s “Machine Learning” here)
5.1 Tiny intent classifier (classical ML)

File: api/ml_intents.py

Model: TfidfVectorizer(1–2 grams) + LinearSVC (scikit-learn).

Task: When the deterministic planner can’t parse the phrasing, the classifier predicts one of 5 intents: list, describe, keys, partitions, other.

Training: In-code seed phrases per intent; you can expand this list or persist a trained model later.

Confidence: Softmax-like score over SVM decision margins (for logging/experiments).

Why this matters: It makes the bot more forgiving to typos and natural phrasing (“show me alert tables”, “what keys on TXN_ALERTS”), while keeping the final query deterministic and safe.

5.2 LLM natural-language generation

File: api/llm.py

Wrapper: LiteLLM → you can switch providers (OpenAI, Azure, Anthropic, Google, or local Ollama) via env only.

Input: The LLM receives only the tool outputs (tables list, relations edges, and “SQL used” for context) plus the user question and schema.

System prompt guardrails: “Explain metadata only, don’t invent or execute SQL, refuse business data.”

Output: A clean, human reply (one paragraph + optional bullets).

Fallback: If an LLM call fails, response_nlg.py creates a good-looking, deterministic summary.

Why this matters: You get human-sounding answers with no risk of the model generating or running SQL against data.

5.3 Relationship explainer (graph-aware reasoning)

File: api/explain.py

What it does: Finds tables matching a keyword (e.g., “ALERT”), discovers FK edges among them, and summarizes connections (e.g., ALERT_HISTORY → TXN_ALERTS via ALERT_ID).

Narration: LLM (or template) converts a set of nodes/edges into plain English: hubs, edge explanations, and a small “table notes” glossary.

Why this matters: Users can ask story-like questions (“how are alert tables connected?”) and get a relationship overview without reading raw dictionary views.

6) API contracts (quick reference)
/chat (LLM replies)

POST { message: str, schema: str, tone?: "friendly"|"formal" }
200 { reply: str, tables?: Row[], sql_snippets?: string[] }

Uses Planner → (optional ML) → DB tools → LLM to narrate.

/explain (relations)

POST { schema: str, keyword: str }
200 { title: str, summary: str, tables: Row[], relations: Edge[], sql_snippets: string[] }

Summarizes tables matching the keyword and their FK/PK relationships.

/ask (deterministic only)

POST { question: str, schema: str }
200 { answer: str, tables?: Row[], sql_snippets?: string[] }

7) Streamlit UI behavior (ui/app.py)

Single page with:

Header card (project badges).

Sidebar: schema field, tone selector, quick prompts, “Explain ALERT tables” action.

Chat area: messages, reply text, Results tab (dataframe), SQL Used tab (audit), Notes tab.

Endpoints used: /chat by default (LLM replies), /explain for relationship discovery; falls back to mock data if API is unreachable.

Typing effect (optional) and tone control (friendly/formal).

8) Deployment & ops

Local dev: pip install -r requirements.txt, set env (DEMO_MODE=1 to avoid DB), run uvicorn app:app --reload.

UI: pip install -r requirements-ui.txt, streamlit run ui/app.py with API_BASE=http://localhost:8000.

Docker: Provided Dockerfile for the API.

CORS: ALLOW_ORIGINS env variable controls allowed UI origins.

Logging: JSON logger via python-json-logger; you can capture {question, schema, sql} for audit.

9) Extending safely

Add intents: In ml_intents.SEED and intents.plan_query() for new tasks (indexes, synonyms, views).

Entity resolution: Recognize common table aliases (party, customer) → map to canonical names before SQL.

Graph view: Render FK edges in the UI (GraphViz/pyvis) as a “Relations” tab for /explain.

Auth: Add a bearer token on /chat//explain; log requester id in every call.

Model registry: If you train a larger intent model, persist it and load on startup.

10) Limitations to be aware of

Metadata-only: By design, it won’t answer questions about data content or metrics inside business tables.

Classifier scope: The tiny TF-IDF model is intentionally simple; you should expand the seed phrases over time for better recall.

Schema naming: The allow-listed schema must be correct (e.g., OFSAAFCCM) or the queries will find nothing.

LLM variability: The LLM’s narration is controlled and grounded, but wording may vary slightly per response (temperature is low).
