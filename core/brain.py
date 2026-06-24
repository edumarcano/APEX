import os
import re
from typing import Any

from dotenv import load_dotenv
from google import genai

from core.config import ENV_PATH, SYSTEM_PROMPT, is_dev_mode

load_dotenv(dotenv_path=ENV_PATH)

_SPEECH_MARKER = "===SPEECH==="
_INSIGHTS_MARKER = "===INSIGHTS==="
_BULLET_PREFIX_RE = re.compile(r"^[\u2022\-\*>\s]+")


def _parse_model_output(text: str) -> tuple[str, list[str]]:
    """Split Gemini output into speech prose and cleaned insight bullet lines."""
    if _INSIGHTS_MARKER in text:
        speech_part, insights_part = text.split(_INSIGHTS_MARKER, 1)
    else:
        speech_part = text
        insights_part = ""

    if _SPEECH_MARKER in speech_part:
        speech_part = speech_part.split(_SPEECH_MARKER, 1)[-1]

    briefing = speech_part.strip()

    insights: list[str] = []
    for line in insights_part.splitlines():
        cleaned_line = _BULLET_PREFIX_RE.sub("", line.strip()).strip()
        if cleaned_line:
            insights.append(cleaned_line)

    return briefing, insights


def _fallback_output(raw_data: str) -> dict[str, Any]:
    """Offline baseline when Gemini synthesis is unavailable."""
    return {
        "briefing": raw_data,
        "insights": ["Telemetry data loaded directly."],
    }


def process_telemetry(raw_data: str) -> dict[str, Any]:
    """
    Configure Gemini with system prompt plus raw telemetry and return structured output.

    Args:
        raw_data: Raw telemetry text injected after the system prompt.

    Returns:
        Mapping with ``briefing`` (TTS prose) and ``insights`` (HUD bullet strings).

    Behavior:
        When DEV_MODE is active, ``DEV_AI_SYNTHESIS`` selects raw bypass, local SLM
        placeholder, or fall-through to the live Gemini client.
        Otherwise loads GEMINI_API_KEY; missing key raises and is caught by the handler below.
        Empty or whitespace-only model responses raise and are caught the same way.
        On any exception (including missing key and empty response), prints diagnostics and
        returns the offline fallback embedding raw_data in ``briefing``.
    """
    if is_dev_mode():
        from core.config import DEV_AI_SYNTHESIS

        if DEV_AI_SYNTHESIS == "raw":
            print(
                "[BRAIN]: DEV_MODE active — DEV_AI_SYNTHESIS=raw; "
                "returning unmodified telemetry."
            )
            return {
                "briefing": f"DEV MODE ACTIVE. Model call bypassed.\n\n{raw_data}",
                "insights": ["DEV MODE: raw telemetry bypass active."],
            }

        if DEV_AI_SYNTHESIS == "slm":
            print(
                "[BRAIN]: DEV_MODE active — DEV_AI_SYNTHESIS=slm; "
                "allocating local placeholder baseline."
            )
            # TODO: — Integrate local SLM fallback execution loop via Ollama.
            return {
                "briefing": (
                    "DEV MODE ACTIVE. Local SLM placeholder briefing.\n\n"
                    f"{raw_data}"
                ),
                "insights": ["DEV MODE: local SLM placeholder active."],
            }

        if DEV_AI_SYNTHESIS == "llm":
            print(
                "[BRAIN]: OPERATIONAL SECURITY ALERT — DEV_MODE with "
                "DEV_AI_SYNTHESIS=llm: engaging live cloud Gemini execution."
            )

    try:
        gemini_key = os.getenv("GEMINI_API_KEY")
        if not gemini_key:
            raise ValueError("Gemini API key is missing.")

        client = genai.Client(api_key=gemini_key)
        full_prompt = f"{SYSTEM_PROMPT}\n\nDATA TO ANALYZE: {raw_data}"

        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=[full_prompt],
        )
        if response.text and response.text.strip():
            briefing, insights = _parse_model_output(response.text.strip())
            if not briefing:
                raise ValueError("Gemini returned an empty speech section.")
            return {
                "briefing": briefing,
                "insights": insights,
            }

        raise ValueError("Gemini returned an empty response.")

    except Exception as e:
        print(f"[BRAIN]: Gemini link failed: ({e}).")
        print("[BRAIN]: Engaging offline fallback protocol...")
        return _fallback_output(raw_data)


if __name__ == "__main__":
    test_data = "Temperature at 82 degrees with scattered clouds."
    print(f"[BRAIN]: {process_telemetry(test_data)}")
