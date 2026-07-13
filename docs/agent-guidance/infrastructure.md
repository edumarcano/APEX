# Infrastructure and Configuration Guidance

- Preserve `launcher.py` as the production entrypoint: FastAPI listens on `127.0.0.1:8000` and the compiled HUD is served on `127.0.0.1:5500`.
- Keep secrets, tokens, credentials, private keys, machine-specific paths, and environment-only switches in `.env`; keep user-facing non-secret settings in `config.json`.
- Use generic documented placeholders in `.env.example` and never copy local secret values or personal absolute paths into tracked files.
- Preserve `DEV_MODE` and `DEMO_MODE` semantics and document any intentional change to environment variables, defaults, or precedence.
- Treat dependency manifests and lockfiles as coordinated artifacts. Make dependency changes intentionally, regenerate the relevant lockfile, and validate the resulting environment.
- Prefer `uv sync --locked` for reproducible Python installs and `uv run` for repository Python commands. Keep `pyproject.toml` and `uv.lock` in sync; do not reintroduce a competing canonical Python requirements manifest.
- Prefer repository-relative paths and cross-platform Python behavior. Keep Windows launcher support when modifying subprocess or path handling.
- Bound subprocess waits, network access, and retries; surface actionable errors and clean up child processes deterministically.
- Avoid infrastructure complexity that is disproportionate to a single-user, local-first application.
- Validate configuration fallbacks, startup behavior, and migration impacts appropriate to the files changed.

