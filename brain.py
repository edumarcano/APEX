import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

APEX_SYSTEM_PROMPT = f"""
You are APEX (Automated Personal Environment Xylem). 
You are an authoritative, high-ranking AI assistant. 
Your user is designated as 'Chief'.

Write a concise, witty briefing in exactly 40 words or less. 
Do not use emojis, asterisks, or markdown formatting (TTS compatibility).
    """


def process_flow(raw_data: str) -> str:
    """
    Configures the Gemini API, injects the provided telemetry data into the system prompt, and returns a formatted briefing.
    Bypasses Gemini API if TEST_MODE is enabled.
    """
    TEST_MODE = os.getenv("TEST_MODE", "false").lower()
    if TEST_MODE == "true":
        print("TEST MODE ENABLED. Bypassing model call.")
        return f"APEX in TEST MODE.\n\n{raw_data}"

    try:
        gemini_key = os.getenv("GEMINI_API_KEY")
        if not gemini_key:
            raise ValueError("Gemini API key is missing.")

        client = genai.Client(api_key=gemini_key)
        full_prompt = f"{APEX_SYSTEM_PROMPT}\n\nDATA TO ANALYZE: {raw_data}"

        response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[full_prompt]
        )
        if response.text and response.text.strip():
            return response.text.strip()
        else:
            raise ValueError("Gemini returned an empty response.")

    except Exception as e:
        print(f"[BRAIN]: Gemini link failed: ({e}).")
        print("[BRAIN]: Engaging offline fallback protocol...")

        return f"""Chief, the primary neural link is experiencing an anomaly. Initiating raw telemetry readout: {raw_data}"""

if __name__ == "__main__":
    test_data = "Environment stabilized at 82 degrees with scattered clouds."
    print(process_flow(test_data))