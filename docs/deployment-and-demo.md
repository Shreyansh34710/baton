# Local deployment and demo

BATON is a local MVP. It runs a FastAPI backend, a React/Vite frontend, SQLite,
and optional local Ollama enrichment. The API client reads public GitHub REST
data without cloning or executing repository code.

## Prerequisites

- Python 3.9 or newer and `pip`.
- Node.js compatible with the Vite version in `frontend/package.json`, plus npm.
- GitHub public API access from the backend host. Unauthenticated rate limits
  apply; the application does not accept a GitHub token.
- Ollama running on the same machine as the backend for AI enrichment. The
  configured model defaults to `qwen3:8b`.

## Start BATON

In terminal 1:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
ollama pull qwen3:8b
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

If Ollama is already installed and running, `ollama pull` only needs to be run
once. Check `http://127.0.0.1:8000/api/v1/health` for API/database health.
SQLite creates `backend/baton.db` by default; keep the database out of Git.

In terminal 2:

```bash
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Open the Vite URL printed by the command (normally
`http://127.0.0.1:5173`). The default backend URL is
`http://127.0.0.1:8000/api/v1`. For another local backend URL, set
`VITE_API_BASE_URL` before starting Vite and add the frontend origin to backend
`CORS_ORIGINS`.

## Configuration

Backend variables are listed in `backend/.env.example`:

- `DATABASE_URL`: SQLAlchemy SQLite URL. The project does not include schema
  migrations; startup creates registered tables.
- `CORS_ORIGINS`: comma-separated exact frontend origins.
- `OLLAMA_BASE_URL`: must use a loopback host; the client disables proxy use.
- `OLLAMA_MODEL`: defaults to `qwen3:8b`.
- `OLLAMA_TIMEOUT_SECONDS`: defaults to 120 seconds.

A backend deployed on another host cannot reach Ollama running only on a
developer's laptop. The MVP deliberately rejects non-loopback Ollama URLs and
does not provide a cloud AI integration. In that deployment, deterministic
analysis can still produce the report and AI enrichment will be unavailable.
Do not expose Ollama to the public internet as a workaround.

## Demo flow

1. Start the backend, Ollama, and frontend as above.
2. Submit a public repository URL. The Milestone 7 live check used
   `https://github.com/fastapi/fastapi`; `https://github.com/pallets/flask` is
   another tested sample. Both use actual public repository data.
3. Show the queued/running stages as BATON collects metadata, repository
   structure, commits, issues/pull requests, contributors, and saves evidence.
4. Open the report when deterministic analysis completes. Demonstrate
   source-linked findings, filtering/search, the evidence drawer, and the
   First-48-Hours checklist. The checklist is stored only in that browser.
5. Explain that deterministic findings are rule-based and may need review.
   AI items, when accepted, are model-generated inferences requiring review.

The live Qwen3:8b checks initially rejected generated items because the schema
did not require the citation arrays. The schema now requires them. Post-fix
cached-evidence runs accepted 3/3 FastAPI, 1/3 Hello-World, and 1/6 Flask items;
the remaining items were rejected for unsupported evidence-to-finding/task
links. Accepted items are still model inferences and require human review. To
show graceful AI-unavailable behavior,
stop local Ollama before submitting a new repository. Deterministic ingestion
and analysis should still complete; AI status should report unavailable/failed.
Automated tests cover this fallback, but a live stopped-service run was not
performed.

## Operational limitations and troubleshooting

- Work runs in FastAPI's in-process background task. Do not run multiple API
  workers. A restart before deterministic results are saved marks that analysis
  failed and asks the user to resubmit. A restart after deterministic results
  are saved preserves those results and marks interrupted AI enrichment failed.
- There is no durable queue, auth, per-user isolation, duplicate-submission
  deduplication, or retry UI. Submitting the same repository creates another
  project/analysis.
- Public GitHub API limits can interrupt ingestion. Wait for the limit window
  or use a different time window; the app does not use credentials to raise it.
- If Ollama is unavailable, verify `ollama list`, then `ollama pull qwen3:8b`
  and `ollama serve`. Check that `.env` uses a loopback URL and a timeout long
  enough for the local machine.
- If the report does not return after refresh, BATON restores the most recent
  submitted analysis ID from browser local storage and fetches its persisted
  status/results again. Clearing site data removes that browser shortcut but
  does not delete the server-side database rows.
