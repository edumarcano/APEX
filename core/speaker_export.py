"""Bounded pyttsx3-to-WAV child process used by reusable briefing audio."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _select_voice(engine: object, gender: str) -> None:
    voices = engine.getProperty("voices")
    if not voices:
        return
    for voice in voices:
        name = (getattr(voice, "name", "") or "").lower()
        voice_id = (getattr(voice, "id", "") or "").lower()
        voice_gender = (getattr(voice, "gender", "") or "").lower()
        terms = (name, voice_id, voice_gender)
        if gender == "male" and any("david" in term or "male" in term for term in terms):
            engine.setProperty("voice", voice.id)
            return
        if gender != "male" and any("zira" in term or "female" in term for term in terms):
            engine.setProperty("voice", voice.id)
            return
    engine.setProperty("voice", voices[0].id)


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    try:
        payload = json.load(sys.stdin)
        text = payload["text"]
        gender = payload["gender"]
        if not isinstance(text, str) or gender not in {"female", "male"}:
            return 2
        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("rate", 175)
        _select_voice(engine, gender)
        output_path = Path(sys.argv[1])
        engine.save_to_file(text, str(output_path))
        engine.runAndWait()
        engine.stop()
        return 0 if output_path.is_file() and output_path.stat().st_size else 3
    except Exception:  # noqa: BLE001
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
