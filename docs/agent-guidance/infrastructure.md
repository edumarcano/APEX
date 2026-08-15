# Infrastructure and Configuration Guidance

- Preserve `launcher.py` as the production entrypoint: FastAPI listens on `127.0.0.1:8000` and the compiled HUD is served on `127.0.0.1:5500`.
- Treat loopback binding as part of the security boundary. The API has no authentication, and CORS does not make a remotely bound service private.
- Keep secrets, tokens, credentials, private keys, credential paths, and environment-only switches in `.env`. Keep tracked non-secret defaults in `config.json`, and keep supported personal or machine-local runtime settings in gitignored `config.local.json`.
- Use generic documented placeholders in `.env.example` and never copy local secret values or personal absolute paths into tracked files.
- Preserve `DEV_MODE` and `DEMO_MODE` semantics and document any intentional change to environment variables, defaults, or precedence.
- Treat dependency manifests and lockfiles as coordinated artifacts. Make dependency changes intentionally, regenerate the relevant lockfile, and validate the resulting environment.
- Prefer `uv sync --locked` for reproducible Python installs and `uv run` for repository Python commands. Keep `pyproject.toml` and `uv.lock` in sync; do not reintroduce a competing canonical Python requirements manifest.
- Prefer repository-relative paths and cross-platform Python behavior. Keep Windows launcher support when modifying subprocess or path handling.
- Bound subprocess waits, network access, and retries; surface actionable errors and clean up child processes deterministically.
- Avoid infrastructure complexity that is disproportionate to a single-user, local-first application.
- Validate configuration fallbacks, startup behavior, and migration impacts appropriate to the files changed.
