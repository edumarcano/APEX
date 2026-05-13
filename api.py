"""
FastAPI application for APEX (Milestone Nexus).

Standalone HTTP surface; no main.py integration yet.
"""

from __future__ import annotations

from typing import Any

import uvicorn
from fastapi import FastAPI


app = FastAPI(title="APEX Nexus")


@app.get("/")
def health_check() -> dict[str, Any]:
    """
    Return a minimal health payload for monitoring and readiness probes.
    """
    return {"status": "online", "system": "APEX Nexus"}


def main() -> None:
    """Run the API server bound to localhost."""
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
