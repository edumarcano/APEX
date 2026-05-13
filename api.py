"""
FastAPI application for APEX (Milestone Nexus).

Standalone HTTP surface; briefing trigger mirrors main.start_apex flow.
"""

from __future__ import annotations

import os
import threading
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException

import brain
import calendar_client
import database
import gmail_client
import google_auth
import news_client
import scanner
import speaker
import sports_client
import weather_client
from config import (
    FEATURE_CALENDAR,
    FEATURE_EMAIL,
    FEATURE_NEWS,
    FEATURE_SPORTS,
    FEATURE_WEATHER,
)

app = FastAPI(title="APEX Nexus")


@app.get("/")
def health_check() -> dict[str, Any]:
    """
    Return a minimal health payload for monitoring and readiness probes.
    """
    return {"status": "online", "system": "APEX Nexus"}


@app.post("/api/v1/trigger")
def trigger_briefing() -> dict[str, Any]:
    """
    HTTP entry point for a full APEX run. Mirrors main.start_apex execution order.
    """
    if not scanner.should_run():
        raise HTTPException(
            status_code=403,
            detail="System gate failed: scanner.should_run() is False.",
        )
    
    TEST_MODE = os.getenv("TEST_MODE", "false").lower()
    SHOWCASE_MODE = os.getenv("SHOWCASE_MODE", "false").lower()
    is_test_mode = TEST_MODE == "true"
    is_showcase_mode = SHOWCASE_MODE == "true"

    if not is_test_mode and not is_showcase_mode:
        database.log_run()

    speaker.speak("System initialized. All modules online.")

    print("[SYSTEM]: Fetching data...")
    if FEATURE_WEATHER:
        weather_report = weather_client.fetch_weather_data()
    else:
        print("[SYSTEM]: Weather module bypassed via user preference")
        weather_report = ""

    if FEATURE_SPORTS:
        sports_report = sports_client.fetch_sports_data()
    else:
        print("[SYSTEM]: Sports module bypassed via user preference")
        sports_report = ""

    if FEATURE_NEWS:
        news_report = news_client.fetch_news_data()
    else:
        print("[SYSTEM]: News module bypassed via user preference")
        news_report = ""

    if is_test_mode or is_showcase_mode or not FEATURE_EMAIL:
        print("[SYSTEM]: Email module bypassed via user preference")
        email_report = ""
    else:
        try:
            email_service = google_auth.get_service('gmail', 'v1')
            email_data = gmail_client.get_unread_gmail_data(email_service)

            count = email_data.get("count", 0)
            items = email_data.get("emails", [])

            recent_emails_str = ", ".join(
                [f"'{e['subject']}' at {e['time']}" for e in items]
            ) if items else "Email Telemetry (24h): No unread emails"

            email_report = f"Email Telemetry: {count} unread primary emails. Most recent: {recent_emails_str}"
        except Exception as e:
            print(f"[SYSTEM]: Email fetch failed: ({e})")
            email_report = "ERROR: Check connection"

    if is_test_mode or is_showcase_mode or not FEATURE_CALENDAR:
        print("[SYSTEM]: Calendar module bypassed via user preference")
        calendar_report = ""
    else:
        try:
            calendar_service = google_auth.get_service('calendar', 'v3')
            calendar_data = calendar_client.get_upcoming_calendar_events(calendar_service)
            calendar_report = (
                "Calendar Telemetry (48h): "
                + " | ".join([f"'{event['summary']}' at {event['start']}" for event in calendar_data])
            ) if calendar_data else "Calendar Telemetry (48h): No upcoming events"
        except Exception as e:
            print(f"[SYSTEM]: Calendar fetch failed: ({e})")
            calendar_report = "ERROR: Check connection"

    unread_records = database.fetch_unread_reminders()
    ids = []
    memory_report = ""
    if unread_records:
        ids = [id for id, _ in unread_records]
        notes = [note for _, note in unread_records]
        notes_str = ", ".join(notes)
        memory_report = f"Pending Reminders: {notes_str}"
    else:
        memory_report = "No pending reminders."
    
    combined_raw_data = f"{weather_report} | {sports_report} | {email_report} | {calendar_report} | {news_report} | {memory_report}"

    print("[SYSTEM]: Synthesizing briefing...")

    # Execute filler audio concurrently to hide the Gemini processing time
    filler_thread = threading.Thread(target=speaker.speak, args=("Generating briefing... Please wait...",))
    filler_thread.start()

    final_briefing = brain.process_telemetry(combined_raw_data)

    filler_thread.join()

    voice_thread = threading.Thread(target=speaker.speak, args=(final_briefing,))
    voice_thread.start()

    if ids:
        database.mark_reminders_read(ids)
    
    return {
    "status": "success",
    "briefing": final_briefing,
    "telemetry": combined_raw_data
}


def main() -> None:
    """Run the API server bound to localhost."""
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
