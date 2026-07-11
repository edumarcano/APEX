# APEX Repository Instructions

## Project Context

- APEX is a local-first personal intelligence HUD with a FastAPI backend, a React/TypeScript frontend, SQLite persistence, and optional external connectors.
- Backend code lives in `core/` and `clients/`; frontend source lives in `frontend/src/`; automated Python coverage lives in `tests/`.
- `launcher.py` starts the backend on `127.0.0.1:8000` and serves the compiled frontend on `127.0.0.1:5500`.
- Preserve offline, `DEV_MODE`, and `DEMO_MODE` behavior unless the requested change explicitly alters those modes.

## Working Agreement

- Inspect the relevant implementation, tests, and documentation before making changes.
- Challenge unsupported assumptions and distinguish repository evidence from inference.
- Treat an explicit request to implement or fix something as authorization to edit in scope; do not add a separate approval gate.
- Match planning and verification effort to the risk and breadth of the change.
- Preserve unrelated user changes and avoid broad refactors during localized work.
- Keep one active implementation owner per branch or worktree. Use isolated worktrees for concurrent editing agents.
- Implement complete behavior rather than placeholder-only paths unless scaffolding is explicitly requested.

## Configuration and Secrets

- Keep user preferences, feature flags, module visibility, persona text, and non-secret runtime settings in `config.json`.
- Keep credentials, tokens, private keys, machine-specific paths, and environment-only switches in `.env`.
- Keep `.env.example` limited to documented generic placeholders. Never add real credentials or personal filesystem paths.
- Do not commit generated credentials, OAuth tokens, databases, caches, audio output, model weights, or build artifacts.

## Validation

- Python changes: run `python -m unittest discover -s tests` and add focused regression coverage when behavior changes.
- Frontend changes: run `npm run lint` and `npm run build` from `frontend/`.
- Documentation or agent-configuration changes: validate referenced paths and metadata, then run `git diff --check`.
- Report commands actually run and any validation that could not be completed.

## Scoped Guidance

- All documentation and repository communication must follow `docs/agent-guidance/writing.md`.
- Backend work must follow `docs/agent-guidance/backend.md`.
- Frontend work must follow `docs/agent-guidance/frontend.md` and `docs/design-system.md` when visual behavior changes.
- Launcher, dependency, environment, or configuration work must follow `docs/agent-guidance/infrastructure.md`.
- Reusable procedures live in `.agents/skills/`; use the smallest relevant skill instead of loading unrelated workflows.

