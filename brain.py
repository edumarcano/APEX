import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()


def process_flow(raw_data: str) -> str:
    """
    Configures the Gemini API, injects the provided telemetry data into the system prompt, and returns a formatted briefing.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "Error: Brain module offline. Missing API key."

    genai.configure(api_key=api_key)
    
    model = genai.GenerativeModel('models/gemini-2.5-flash')

    prompt = f"""You are APEX (Automated Personal Environment Xylem). 
    You are an authoritative, high-ranking AI assistant. 
    Your user is designated as 'Chief'.
    
    Write a concise, witty briefing in exactly 40 words or less. 
    Do not use emojis, asterisks, or markdown formatting, as this text will be read aloud by a TTS engine.
    
    Incorporate the following raw data into your briefing:
    {raw_data}"""

    try:
        response = model.generate_content(prompt)
        if response.text:
            return response.text.strip()
        else:
            return "Flow anomaly: Gemini returned an empty response."
    except Exception as e:
        print(f"DEBUG ERROR: {e}")
        return "Flow interrupted. Brain module failed to synthesize data."

if __name__ == "__main__":
    test_data = "Environment stabilized at 82 degrees with scattered clouds."
    print(process_flow(test_data))