import scanner
import weather_client
import speaker
import brain
import sports_client
import gui
import gmail_client
import calendar_client
import news_client
import google_auth
import threading
import database
import os
from config import FEATURE_WEATHER, FEATURE_SPORTS, FEATURE_NEWS, FEATURE_EMAIL, FEATURE_CALENDAR

def start_apex():
    """
    Starts the primary execution loop of the APEX system, validates system state via the scanner,
    aggregates telemetry data from weather, sports, email, and database, and processes the data through
    the Gemini brain model to output a synchronized audio and visual briefing.
    """
    if not scanner.should_run():
        return
    
    TEST_MODE = os.getenv("TEST_MODE", "false").lower()
    SHOWCASE_MODE = os.getenv("SHOWCASE_MODE", "false").lower()
    is_test_mode = TEST_MODE == "true"
    is_showcase_mode = SHOWCASE_MODE == "true"

    if not is_test_mode and not is_showcase_mode:
        database.log_run()

    speaker.speak("Environment scanned. APEX is online.")

    print("Establishing data roots...")
    if FEATURE_WEATHER:
        weather_report = weather_client.fetch_weather_root()
    else:
        weather_report = "Weather data: BYPASSED"

    if FEATURE_SPORTS:
        sports_report = sports_client.fetch_sports_data()
    else:
        sports_report = "Sports data: BYPASSED"

    if FEATURE_NEWS:
        news_report = news_client.fetch_news_data()
    else:
        news_report = "News data: BYPASSED"

    if is_test_mode or is_showcase_mode or not FEATURE_EMAIL:
        email_report = "Email data: BYPASSED"
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
        calendar_report = "Calendar data: BYPASSED"
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

    print("Processing Flow...")

    # Execute filler audio concurrently to hide the Gemini processing time
    filler_thread = threading.Thread(target=speaker.speak, args=("Analyzing telemetry... Stand by...",))
    filler_thread.start()

    final_briefing = brain.process_flow(combined_raw_data)

    filler_thread.join()

    voice_thread = threading.Thread(target=speaker.speak, args=(final_briefing,))
    voice_thread.start()
    gui.launch_environment(final_briefing)

    if ids:
        database.mark_reminders_read(ids)
    
    print("\n--- Briefing Complete ---")

if __name__ == "__main__":
    start_apex()