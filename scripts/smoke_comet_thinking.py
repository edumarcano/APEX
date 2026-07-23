"""
Live Comet thinking-level smoke check.

Verifies gemini-3.5-flash-lite accepts ThinkingConfig(thinking_level="minimal")
before release. Requires GEMINI_API_KEY in the environment or .env.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.agent.providers.gemini_models import GEMINI_MODEL_PROFILES  # noqa: E402
from core.config import ENV_PATH  # noqa: E402

load_dotenv(dotenv_path=ENV_PATH)


def main() -> int:
    comet = GEMINI_MODEL_PROFILES["comet"]
    if comet.thinking_level != "minimal":
        print(
            f"[SMOKE][FAIL] Comet thinking_level expected 'minimal', "
            f"got {comet.thinking_level!r}"
        )
        return 1

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[SMOKE][FAIL] GEMINI_API_KEY is missing.")
        return 1

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=comet.api_model,
        contents=["Reply with exactly: ok"],
        config=types.GenerateContentConfig(
            temperature=0.0,
            thinking_config=types.ThinkingConfig(
                thinking_level=comet.thinking_level,
            ),
        ),
    )

    text = (response.text or "").strip()
    if not text:
        print("[SMOKE][FAIL] Comet returned an empty response.")
        return 1

    print(
        f"[SMOKE][PASS] Comet ({comet.api_model}) accepted "
        f"thinking_level={comet.thinking_level!r}; response={text!r}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
