# BATON foundation architecture

BATON is a modular monolith with a Vite React frontend and a FastAPI backend.
The frontend owns presentation and later calls versioned REST endpoints. The
backend owns configuration, database sessions, API routes, and business
services. `Project` stores a validated GitHub repository URL. `Analysis` belongs
to a project and tracks queued/running/completed/failed state, progress, stage,
timestamps, and optional error details. On submission, a FastAPI background
task owns a database session and collects public GitHub evidence through fixed
REST API routes. `Evidence` rows are linked to both project and analysis.
The worker then runs a deterministic, evidence-only analysis service and
persists findings and onboarding tasks in one `AnalysisResult` JSON row per
analysis. The record contains stable finding IDs, claim/evidence status,
confidence, evidence IDs, evidence source references, and the First-48-Hours
Plan. After deterministic results are persisted, a separate `AIEnrichment`
record tracks local Ollama status and output. The Ollama client sends bounded
evidence packets to a loopback-only HTTP endpoint using structured JSON output.
Output validation rejects unknown IDs, downgrades model-declared facts to
unverified inferences, and marks uncited claims unknown. All AI items require
human review. Deterministic results are never overwritten. If Ollama fails,
the deterministic analysis remains completed and the AI record carries a safe
failed or partial status.

The API exposes `GET /api/v1/health`, `POST /api/v1/projects`, and
`GET /api/v1/analyses/{analysis_id}`. SQLite tables are created at application
startup from registered SQLAlchemy models, including `repository_evidence`,
`analysis_results`, and `ai_enrichments`. There is no formal migration
framework in this MVP. `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, and
`OLLAMA_TIMEOUT_SECONDS` configure the local runtime. The client rejects
non-loopback hosts and disables environment proxy use so repository data is
not sent to a cloud AI endpoint. API pagination is constructed locally and
bounded; repository content is treated as untrusted and arbitrary URLs from
GitHub responses are never fetched. Retries are bounded to transient network
and server errors; public API rate limits fail safely for user retry.
`GET /analyses/{id}/results` returns deterministic results; related endpoints
provide filtered findings, risks, contributors, and plan tasks. AI endpoints
return separate enrichment, decision, risk-explanation, status, and enriched
plan data. Rules and model reasoning can miss context; AI items remain
unreviewed inferences and must not be treated as verified facts. The report
dashboard consumes the complete results endpoint and AI enrichment endpoint
once on completion. Repository metadata is loaded from its stored evidence
record; other evidence content is fetched on demand through
`GET /analyses/{id}/evidence/{evidence_id}`. That endpoint checks that evidence
belongs to the requested analysis and returns stored content plus deterministic
finding references. The frontend validates GitHub URLs before opening them in a
new tab. Search and category filters run on loaded data; checklist completion
is held in browser local storage and is not synchronized to SQLite. Project
technology indicators use only the bounded sample of selected source-file
paths, not a full dependency scan.

Milestone 7 bounds GitHub response bodies, handles repositories without a
default branch, recovers queued/running analyses on startup, and restores the
latest report from browser local storage after refresh. Ollama prompt references
use request-local short aliases mapped back to stored database IDs before
persistence.

The API uses FastAPI in-process background tasks, not a durable worker. Startup
marks interrupted jobs without saved deterministic results failed; if
deterministic output was saved before restart, the output remains available and
AI enrichment is closed as interrupted. Run one API process. There is no
cross-worker coordination or duplicate-repository deduplication. A remote
deployment cannot access Ollama on a developer laptop: Ollama URLs are restricted
to loopback and there is no cloud inference fallback. Live diagnostics found
that Qwen omitted citation arrays because the structured schema treated them
as optional. Reference arrays are now required and safe rejection categories
are persisted and returned by the enrichment/status endpoints. Post-fix live
samples accepted 3/3 FastAPI items, 1/3 Hello-World items, and 1/6 Flask items;
other cited items were rejected because their evidence did not support the
selected findings/tasks. All accepted items still require human review. See `deployment-and-demo.md` for run/demo instructions and
`milestone7-verification.md` for recorded checks.
