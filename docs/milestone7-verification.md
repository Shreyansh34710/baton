# Milestone 7 verification record

**Repository:** BATON checkout; **branch:** `main`.
**Verification date:** 2026-11-10

## Audit and changes

The existing workflow is a React dashboard calling a FastAPI API. The API
creates project/analysis records, runs public GitHub ingestion in a FastAPI
in-process background task, persists bounded evidence in SQLite, writes a
deterministic analysis, then separately attempts local Ollama enrichment. The
dashboard retrieves persisted results and evidence on completion.

The audit identified restart loss for active in-process tasks, no restoration
of a completed report after refresh, missing default-branch handling for empty
repositories, and unbounded GitHub response-body reads. Those reliability gaps
were addressed. Qwen-generated references were rejected on the first live
samples; request-scoped aliases alone did not solve the problem. A captured
raw response later identified optional citation arrays in the structured schema
as the cause; the schema is now strict and a bounded post-fix live run accepted
all three generated FastAPI items.

## Live repository workflow checks

The app was exercised through a FastAPI `TestClient` using a temporary SQLite
database and live public GitHub API requests. Each run created a project and
analysis, ingested repository data, persisted evidence, generated deterministic
findings and onboarding tasks, attempted real local `qwen3:8b` enrichment, and
retrieved results/status/evidence through API routes. The harness limited
selected source files to six per run (the product limit is 20) to bound the
live test. It did not use a PEP/document or cloud AI service.

| Public repository | Observed persisted result | Qwen outcome (before citation-schema fix) |
| --- | --- | --- |
| [octocat/Hello-World](https://github.com/octocat/Hello-World) | Completed; 209 evidence rows, 386 deterministic findings, 4 plan tasks | 0 accepted, 3 rejected |
| [pallets/flask](https://github.com/pallets/flask) | Completed; 409 evidence rows, 339 deterministic findings, 4 plan tasks | 0 accepted, 5 rejected |
| [fastapi/fastapi](https://github.com/fastapi/fastapi) | Completed; 326 evidence rows, 434 deterministic findings, 3 plan tasks | 0 accepted, 5 rejected |

For all three runs, deterministic findings referenced existing evidence and the
evidence detail endpoint returned HTTP 200. These counts describe the saved
test outputs and are not correctness scores. Ingestion completion proves the
workflow ran; it does not establish that every heuristic conclusion is right.

The earlier alias-only follow-up reused stored FastAPI evidence and returned 0
accepted / 3 rejected. A later diagnostic reproduction captured the raw
response: it was valid JSON with three items, but every item omitted
`evidence_ids`, `finding_ids`, and `plan_task_ids`. The Pydantic schema gave
those arrays empty defaults, so they were optional in the Ollama JSON Schema.
Parsing therefore succeeded; validation rejected each item because no finding
alias was supplied. There was no evidence of a thinking-prefix, malformed JSON,
truncation, or alias translation defect in that response.

The fix makes all three arrays schema-required, requires at least one evidence
and finding alias, and still validates each alias and its evidence/finding/task
relationships before mapping back to stored IDs. After this fix, one bounded
live `qwen3:8b` call reused the stored FastAPI evidence: **3 generated, 3
accepted, 0 rejected**. All rejection-reason counts were zero. The three items
were persisted to the temporary evaluation database and retrieved through
`GET /api/v1/analyses/{analysis_id}/ai-enrichment` with HTTP 200; the API
returned 3 items and matching counts. The exact request prompt and raw response
were inspected from temporary files, not added to the repository.

## Final pre-submission live retest

Using the same cached SQLite evidence and local `qwen3:8b`, the two requested
repositories were retried after the schema fix. No additional GitHub requests
were made.

| Repository | Generated | Accepted | Rejected | Rejection reason | Status | API persistence check |
| --- | ---: | ---: | ---: | --- | --- | --- |
| [octocat/Hello-World](https://github.com/octocat/Hello-World) | 3 | 1 | 2 | `unsupported_reference`: 2 | partial | HTTP 200; counts match; 1 item returned |
| [pallets/flask](https://github.com/pallets/flask) | 6 | 1 | 5 | `unsupported_reference`: 5 | partial | HTTP 200; counts match; 1 item returned |

For both samples, accepted evidence, finding, and task IDs resolved within the
same analysis. The deterministic result was unchanged. The validator rejected
model citations when their selected findings/tasks did not support those
evidence IDs; validation was not loosened. Detailed raw output was not saved
for these two runs, so the precise citation pair causing each unsupported
reference cannot be reported beyond the validator's safe `unsupported_reference`
category.

The live `TestClient` completed background work before the response was
observed; it did not demonstrate intermediate progress in an actual browser.
No live test explicitly stopped Ollama or induced a real GitHub outage. Those
failure paths are covered by mocked automated tests only.

## Automated checks

Commands run for this record:

```bash
cd backend
./.venv/bin/python -m pytest -p no:cacheprovider tests -q
cd ../frontend
npm test -- --run
npm run build
npm audit
cd ..
git diff --check
```

Observed results on 2026-11-10:

- Backend: **67 passed**.
- Frontend: **15 passed** across 2 test files.
- Production build: **passed** (TypeScript and Vite).
- `npm audit`: **0 vulnerabilities**.
- `git diff --check`: **passed**, no output.

Mocked backend coverage includes invalid URLs, 404, rate limiting, retry and
network failures, redirects, oversized bodies, missing README, empty repository,
partial metadata, file exclusions/limits, evidence persistence, deterministic
analysis, restart recovery, Ollama malformed/unavailable/timeout responses,
and citation validation. Frontend tests cover submission/report rendering and
report restoration. These tests do not substitute for the live model failures
above.

## Browser and security review

The computer-use browser inventory reported no browser because the browser
access host was unavailable. There was no interactive browser verification or
screenshot capture. Frontend behavior was verified through unit tests and the
production build only.

Reviewed controls: HTTPS `github.com` repository URL validation; fixed GitHub
API routes and locally constructed pagination; redirects disabled; bounded
timeouts/retries and response size; capped evidence/file selection; exclusions
for binary, generated, dependency, lock, and likely secret files; no repository
code execution or arbitrary content URL fetching; safe API errors; evidence
lookup constrained to the requested analysis; Ollama constrained to loopback
with proxy environment disabled; prompt content treated as untrusted; unknown
AI references rejected; and CORS limited to configured exact origins with
credentials disabled. Local storage contains only the latest analysis pointer,
repository URL, and report checklist state; it is not authentication. BATON has
no user authentication or authorization and is not suitable for exposing
private project data to untrusted users.

## Reliability limits and readiness

- Work remains in-process. Do not run multiple API workers. A restart before
  deterministic results are saved marks the analysis failed for resubmission.
  If results are already saved, they are preserved and interrupted AI work is
  closed as failed. This is recovery, not job resumption.
- Duplicate submissions are not deduplicated. There is no formal DB migration
  framework or user authentication.
- Browser report restoration is best-effort and only remembers the latest
  analysis in that browser.
- Public GitHub unauthenticated rate limits apply.
- The live schema fix produced 3/3 accepted Qwen items on FastAPI, but only 1/3
  on Hello-World and 1/6 on Flask. This confirms the missing-array defect is
  fixed, while reference relevance remains inconsistent across samples. AI
  items remain unverified inferences requiring human review. No cloud inference
  fallback exists.
- Browser validation was unavailable in this environment.

**Readiness assessment:** deterministic ingestion/reporting and the corrected
AI reference path accepted and persisted items on all three post-fix samples,
but it rejected most generated items for unsupported evidence/finding links on
two repositories. The pipeline is demonstrably functioning; enrichment
relevance remains inconsistent and needs honest disclosure in a demo. This is
not proof of general model reliability.
Browser validation remains unperformed. Deployment/demo setup is in
`deployment-and-demo.md`.
