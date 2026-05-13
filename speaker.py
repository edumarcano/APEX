import base64
import binascii
import os
from typing import Any

import pyttsx3
import requests


def _infer_language_code(voice_id: str) -> str:
    """Infer a BCP-47 language code from a Google voice identifier."""
    parts = voice_id.split("-")
    if len(parts) >= 2 and len(parts[0]) == 2 and len(parts[1]) == 2:
        return f"{parts[0]}-{parts[1]}"
    return "en-US"


def fetch_google_audio(text: str, voice_id: str) -> bytes:
    """Synthesize ``text`` with Google Cloud TTS and return MP3 bytes."""
    from google.cloud import texttospeech

    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code=_infer_language_code(voice_id),
        name=voice_id,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
    )
    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    )
    return response.audio_content


def fetch_inworld_audio(text: str, voice_id: str) -> bytes:
    """Synthesize text using Inworld TTS and return decoded audio bytes."""
    api_key = os.getenv("INWORLD_API_KEY")
    if not api_key:
        raise RuntimeError("INWORLD_API_KEY is not set.")

    response = requests.post(
        "https://api.inworld.ai/tts/v1/voice",
        auth=(api_key, ""),
        json={
            "text": text,
            "voiceId": voice_id,
            "modelId": "inworld-tts-1.5-max",
        },
        timeout=30,
    )
    response.raise_for_status()

    data: dict[str, Any] = response.json()
    audio_content = data.get("audioContent")
    if not isinstance(audio_content, str):
        raise ValueError("Inworld response did not include a valid audioContent field.")

    try:
        return base64.b64decode(audio_content, validate=True)
    except binascii.Error as exc:
        raise ValueError("Inworld audioContent is not valid base64.") from exc


def initialize_engine():
    """
    Initializes the text-to-speech engine and sets the speed and voice.
    Returns:
        pyttsx3.Engine: The initialized engine.
    """
    engine = pyttsx3.init()
    
    engine.setProperty('rate', 175) 
    
    voices = engine.getProperty('voices')
    engine.setProperty('voice', voices[0].id) 
    
    return engine


def speak(text: str) -> None:
    """
    Speaks the given text using the text-to-speech engine.
    Args:
        text (str): The text to speak.
    """
    engine = initialize_engine()
    
    print(f"\n[SPEAKER]: {text}")
    
    engine.say(text)
    engine.runAndWait()

if __name__ == "__main__":
    speak("System audio test. Speaker operational.")