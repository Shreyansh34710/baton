# BATON

BATON is an AI-powered GitHub project knowledge and developer handover system.

## Milestone status

Milestone 1 established the React/Vite frontend and FastAPI/SQLite backend.
Milestone 2 adds GitHub project submission and persisted analysis lifecycle
tracking. Milestone 3 adds bounded, unauthenticated read-only ingestion of
public GitHub metadata, repository structure, selected text files, and recent
activity. Milestone 4 analyzes persisted evidence with deterministic rules,
stores source-linked findings and a preliminary First-48-Hours Plan, and
exposes results through the analysis API. No AI model is used for this stage;
heuristic findings are labeled as inferences or unknowns where appropriate.
Milestone 5 adds optional local Ollama enrichment in a separate persisted
record. Deterministic findings remain unchanged; model-generated items are
unverified inferences or unknowns and require human review. Milestone 6 adds a
report dashboard for persisted deterministic and AI results, with on-demand
evidence inspection and a browser-local First-48-Hours checklist. Milestone 7
adds restart recovery for interrupted in-process work, bounded GitHub response
bodies, empty-repository handling, and restoration of the latest report after a
browser refresh. The worker is still in-process and is not a durable job queue.
Live Qwen3:8b diagnostics found that reference arrays were optional in the
structured schema, so the model omitted them. They are now required, with safe
rejection-reason counts. Post-fix live samples accepted 3/3 items for FastAPI,
1/3 for Hello-World, and 1/6 for Flask; the rest were rejected for unsupported
evidence-to-finding links. See [deployment and demo instructions](docs/deployment-and-demo.md)
and the [Milestone 7 verification report](docs/milestone7-verification.md).

## Run locally

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API provides `POST /api/v1/projects` to create a project and queue ingestion,
`GET /api/v1/analyses/{analysis_id}` to retrieve lifecycle status, and
`GET /api/v1/health` for health checks. Ingestion uses the public GitHub REST
API, never clones or executes repository code, and stores capped evidence in
SQLite. It is limited to 100 commits, 100 issues, 100 pull requests, 100
contributors, 200 tree entries, 20 selected text files, and 100 KB per file.
GitHub rate limits or unavailable required endpoints fail the analysis with a
safe error. The MVP has no authentication, durable job queue, or automatic retry
UI. On restart, queued/running work without saved deterministic results is
marked failed for resubmission; if deterministic results were saved, they are
preserved and interrupted AI enrichment is marked failed.
After ingestion, deterministic analysis records overview, completion and
ongoing signals, unfinished work, explicit decision statements, contributor
activity, potential risks, and knowledge gaps. Analysis results are persisted
in SQLite and are available at `/api/v1/analyses/{analysis_id}/results`, with
category, risk, contributor, and plan endpoints under that path. Closed issues
and merged pull requests are recorded as events, not proof that a full feature
is complete. Pattern-based detection can miss context and should be reviewed.

AI enrichment uses the local Ollama HTTP API only. `OLLAMA_BASE_URL` defaults
to `http://localhost:11434` and must resolve to a loopback host; `OLLAMA_MODEL`
defaults to `qwen3:8b`; and `OLLAMA_TIMEOUT_SECONDS` defaults to `120`. For the
default model, install and start Ollama locally, then run `ollama pull qwen3:8b`.
The backend sends a bounded evidence packet (maximum 48 KB) with a structured
JSON schema. It validates evidence and finding IDs; fabricated references are
discarded, uncited claims become unknown, and model-declared facts are
downgraded to inferences pending human review. AI results are stored separately
in `ai_enrichments`. If Ollama fails, the analysis remains completed when
deterministic analysis succeeded, while AI enrichment is marked failed and the
status flow reports partial completion. AI results are available at
`/api/v1/analyses/{analysis_id}/ai-enrichment`, with dedicated endpoints for
status, decisions, risk explanations, and the enriched plan. Automated tests
mock Ollama. Post-fix live Qwen3:8b calls produced partial enrichment for all
three cached samples. All accepted items are unverified model inferences
requiring human review; unsupported evidence/finding links are rejected.

Milestone 6 adds the evidence-backed developer handover dashboard described
below. It uses persisted deterministic and AI results and opens stored evidence
on demand; it does not generate or claim a completed report until the backend
analysis results are available.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The Vite development server runs at `http://127.0.0.1:5173` by default. After
an analysis finishes, the dashboard loads persisted results and displays an
overview, project understanding, work status, decisions, contributors, risks,
knowledge gaps, and the First-48-Hours Plan. Search and category filters are
client-side. Evidence references open a drawer that fetches the stored excerpt
from `GET /api/v1/analyses/{analysis_id}/evidence/{evidence_id}`. AI explanations
remain labeled as model-generated inferences requiring review; deterministic
findings and AI enrichment are presented separately. Plan checkboxes are saved
in the current browser's local storage, not to the BATON server.

## Tests

```bash
cd backend && pytest
cd frontend && npm test -- --run
```

## Configuration

Copy `backend/.env.example` to `backend/.env` when local overrides are needed.
No API token or cloud AI credential is required.
