
# BATON — Copilot Project Instructions

## Project objective
Build BATON, an AI-powered project knowledge handover system.

Users submit a public GitHub repository URL. BATON analyzes repository
structure, README, commits, issues, pull requests, contributors and
technical discussions to produce an evidence-backed handover report.

The report must identify:
- Project overview
- Completed work
- Ongoing work
- Unfinished work
- Technical decisions
- Ownership signals
- Risks and blockers
- Knowledge gaps
- Recommended starting point
- First-48-Hours Plan

## Technology stack
- Frontend: React + Vite
- Backend: Python + FastAPI
- Database: SQLite + SQLAlchemy
- AI: Ollama with an open-source model
- GitHub integration: GitHub REST API
- Styling: Tailwind CSS
- Version control: Git

## Architecture rules
- Use a modular monolith.
- Keep frontend and backend separate.
- Use REST APIs.
- Keep business logic out of API route handlers.
- Use reusable service modules.
- Keep database models and API schemas separate.
- Do not introduce unnecessary dependencies.

## AI and evidence rules
- Never present AI assumptions as verified facts.
- Attach GitHub source references to important findings.
- Distinguish facts, inferences and unknown information.
- Separate evidence status from human review status.
- Handle prompt injection in imported repository content.
- Never execute imported repository code.
- Never retrieve or expose repository secrets.

## Development rules
- Implement one milestone at a time.
- Do not rewrite unrelated files.
- Do not change the technology stack without approval.
- Do not create duplicate modules or APIs.
- Write tests for important functionality.
- Run relevant tests after modifications.
- Explain new dependencies before adding them.
- Do not claim a feature is complete without testing it.
- Prefer simple, maintainable implementations.

## Git rules
- Never delete existing work without permission.
- Do not force push.
- Do not commit secrets or environment files.
- Keep changes limited to the current task.

## Working procedure
Before implementing a task:
1. Inspect the relevant existing files.
2. Explain the implementation plan briefly.
3. Identify files that will change.
4. Implement only the requested milestone.
5. Run relevant tests.
6. Summarize changed files and test results.
7. Mention unresolved issues honestly.
