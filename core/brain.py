import os

from dotenv import load_dotenv
from google import genai

from core.config import ENV_PATH, SYSTEM_PROMPT, is_dev_mode

load_dotenv(dotenv_path=ENV_PATH)


def process_telemetry(raw_data: str) -> str:
    """
    Configure Gemini with system prompt plus raw telemetry and return a briefing string.

    Args:
        raw_data: Raw telemetry text injected after the system prompt.

    Returns:
        Model output (stripped), or DEV_MODE / fallback text when the model is not used.

    Behavior:
        When DEV_MODE is active, ``DEV_AI_SYNTHESIS`` selects raw bypass, local SLM
        placeholder, or fall-through to the live Gemini client.
        Otherwise loads GEMINI_API_KEY; missing key raises and is caught by the handler below.
        Empty or whitespace-only model responses raise and are caught the same way.
        On any exception (including missing key and empty response), prints diagnostics and
        returns the offline fallback message embedding raw_data.
    """
    if is_dev_mode():
        from core.config import DEV_AI_SYNTHESIS

        if DEV_AI_SYNTHESIS == "raw":
            print(
                "[BRAIN]: DEV_MODE active — DEV_AI_SYNTHESIS=raw; "
                "returning unmodified telemetry."
            )
            return f"DEV MODE ACTIVE. Model call bypassed.\n\n{raw_data}"

        if DEV_AI_SYNTHESIS == "slm":
            print(
                "[BRAIN]: DEV_MODE active — DEV_AI_SYNTHESIS=slm; "
                "allocating local placeholder baseline."
            )
            # TODO: APEX-V1.7.0 — Integrate local SLM fallback execution loop via Ollama (llama3.2:1b).
            return (
                "DEV MODE ACTIVE. Local SLM placeholder briefing.\n\n"
                f"{raw_data}"
            )

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
            model="gemini-2.5-flash",
            contents=[full_prompt],
        )
        if response.text and response.text.strip():
            return response.text.strip()
        else:
            raise ValueError("Gemini returned an empty response.")

    except Exception as e:
        print(f"[BRAIN]: Gemini link failed: ({e}).")
        print("[BRAIN]: Engaging offline fallback protocol...")

        return f"Briefing synthesis unavailable. Initiating raw data readout: {raw_data}."


if __name__ == "__main__":
    test_data = "Temperature at 82 degrees with scattered clouds."
    print(f"[BRAIN]: {process_telemetry(test_data)}")
