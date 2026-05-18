"""
FastAPI application for APEX (Milestone Nexus).

Standalone HTTP surface; briefing trigger mirrors main.start_apex flow.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from clients import (
    calendar_client,
    gmail_client,
    google_auth,
    news_client,
    sports_client,
    weather_client,
)
from core import brain, database, scanner, speaker
from core.config import (
    ENV_PATH,
    FEATURE_CALENDAR,
    FEATURE_EMAIL,
    FEATURE_NEWS,
    FEATURE_SPORTS,
    FEATURE_WEATHER,
)

load_dotenv(dotenv_path=ENV_PATH)

app = FastAPI(title="APEX Nexus")


DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
)


def get_allowed_origins() -> list[str]:
    """Return allowed CORS origins from env, or local defaults."""
    configured_origins = os.getenv("APEX_ALLOWED_ORIGINS", "").strip()
    if not configured_origins:
        return list(DEFAULT_ALLOWED_ORIGINS)

    parsed_origins = [
        origin.strip() for origin in configured_origins.split(",")
    ]
    filtered_origins = [origin for origin in parsed_origins if origin]
    return filtered_origins or list(DEFAULT_ALLOWED_ORIGINS)


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PipelineState:
    """
    Thread-safe pipeline progress for diagnostics and lifecycle checkpoints.

    Internal fields track step index, phase label, last UTC timestamp ISO string,
    and whether a run currently holds active status for `/api/v1/status` probing.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._is_active = False
        self._step = 0
        self._label = "IDLE"
        self._timestamp = datetime.now(timezone.utc).isoformat()

    def update(self, step: int, label: str) -> None:
        """
        Advance the conceptual pipeline stage.

        Args:
            step: Monotonic pipeline step index supplied by orchestration logic.
            label: Stable short label naming the stage for dashboards and probes.
        """
        with self._lock:
            self._is_active = True
            self._step = step
            self._label = label
            self._timestamp = datetime.now(timezone.utc).isoformat()

    def reset(self) -> None:
        """Restore the tracker to idle or pre-run defaults."""
        with self._lock:
            self._is_active = False
            self._step = 0
            self._label = "IDLE"
            self._timestamp = datetime.now(timezone.utc).isoformat()

    def get_state(self) -> dict[str, Any] | None:
        """
        Produce a shallow snapshot suitable for `/api/v1/status` responses.

        Returns:
            Mapping for JSON serialization, or None when no active run is recorded.
        """
        with self._lock:
            if not self._is_active:
                return None
            return {
                "step": self._step,
                "label": self._label,
                "timestamp": self._timestamp,
            }


global_pipeline_state = PipelineState()


@app.get("/")
def health_check() -> dict[str, Any]:
    """
    Return a minimal health payload for monitoring and readiness probes.
    """
    return {"status": "online", "system": "APEX Nexus"}


@app.get("/api/v1/status")
def get_pipeline_diagnostic_status() -> dict[str, Any]:
    """
    Diagnostic snapshot keyed off global_pipeline_state for operators and probes.
    """
    snapshot = global_pipeline_state.get_state()
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail="No active pipeline run. System is OFFLINE.",
        )
    return snapshot


@app.post("/api/v1/trigger")
def trigger_briefing() -> dict[str, Any]:
    """
    HTTP entry point for a full APEX run.

    Mirrors main.start_apex execution order.
    """
    global_pipeline_state.update(1, "GATE")

    if not scanner.should_run():
        global_pipeline_state.reset()
        raise HTTPException(
            status_code=403,
            detail="System gate failed: scanner.should_run() is False.",
        )

    try:
        test_mode = os.getenv("TEST_MODE", "false").lower()
        showcase_mode = os.getenv("SHOWCASE_MODE", "false").lower()
        is_test_mode = test_mode == "true"
        is_showcase_mode = showcase_mode == "true"

        if not is_test_mode and not is_showcase_mode:
            database.log_run()

        speaker.speak("System initialized. All modules online.")

        global_pipeline_state.update(2, "COLLECTION")
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
                email_service = google_auth.get_service("gmail", "v1")
                email_data = gmail_client.get_unread_gmail_data(email_service)

                count = email_data.get("count", 0)
                items = email_data.get("emails", [])

                if items:
                    recent_emails = [
                        f"'{email['subject']}' at {email['time']}"
                        for email in items
                    ]
                    recent_emails_str = ", ".join(recent_emails)
                else:
                    recent_emails_str = (
                        "Email Telemetry (24h): No unread emails"
                    )

                email_report = (
                    f"Email Telemetry: {count} unread primary emails. "
                    f"Most recent: {recent_emails_str}"
                )
            except Exception as exc:
                print(f"[SYSTEM]: Email fetch failed: ({exc})")
                email_report = "ERROR: Check connection"

        if is_test_mode or is_showcase_mode or not FEATURE_CALENDAR:
            print("[SYSTEM]: Calendar module bypassed via user preference")
            calendar_report = ""
        else:
            try:
                calendar_service = google_auth.get_service("calendar", "v3")
                calendar_data = calendar_client.get_upcoming_calendar_events(
                    calendar_service
                )
                if calendar_data:
                    calendar_entries = [
                        f"'{event['summary']}' at {event['start']}"
                        for event in calendar_data
                    ]
                    calendar_report = (
                        "Calendar Telemetry (48h): "
                        + " | ".join(calendar_entries)
                    )
                else:
                    calendar_report = (
                        "Calendar Telemetry (48h): No upcoming events"
                    )
            except Exception as exc:
                print(f"[SYSTEM]: Calendar fetch failed: ({exc})")
                calendar_report = "ERROR: Check connection"

        unread_records = database.fetch_unread_reminders()
        ids = []
        memory_report = ""
        if unread_records:
            ids = [record_id for record_id, _ in unread_records]
            notes = [note for _, note in unread_records]
            notes_str = ", ".join(notes)
            memory_report = f"Pending Reminders: {notes_str}"
        else:
            memory_report = "No pending reminders."

        combined_raw_data = (
            f"{weather_report} | {sports_report} | {email_report} | "
            f"{calendar_report} | {news_report} | {memory_report}"
        )

        global_pipeline_state.update(3, "SYNTHESIS")
        print("[SYSTEM]: Synthesizing briefing...")

        # Execute filler audio concurrently to hide the Gemini processing time
        filler_thread = threading.Thread(
            target=speaker.speak,
            args=("Generating briefing... Please wait...",),
        )
        filler_thread.start()

        final_briefing = brain.process_telemetry(combined_raw_data)

        filler_thread.join()

        global_pipeline_state.update(4, "DELIVERY")
        voice_thread = threading.Thread(
            target=speaker.speak,
            args=(final_briefing,),
        )
        voice_thread.start()

        if ids:
            database.mark_reminders_read(ids)

        return {
            "status": "success",
            "briefing": final_briefing,
            "telemetry": {
                "weather": weather_report,
                "sports": sports_report,
                "news": news_report,
                "email": email_report,
                "calendar": calendar_report,
                "reminders": memory_report,
            },
        }
    finally:
        global_pipeline_state.reset()


def main() -> None:
    """Run the API server bound to localhost."""
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
