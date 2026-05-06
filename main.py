import scanner
import weather_client
import speaker
import brain
import sports_client
import gui
import gmail_client
import threading
import database
import os


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
    weather_report = weather_client.fetch_weather_root()
    sports_report = sports_client.fetch_sports_root()

    if is_test_mode or is_showcase_mode:
        email_report = "Email Telemetry: MOCKED (Bypass active)"
    else:
        try:
            credentials = gmail_client.authenticate_gmail()
            email_data = gmail_client.get_unread_gmail_data(credentials)

            count = email_data.get("count", 0)
            items = email_data.get("emails", [])

            if items:
                summary_list = [f"'{e['subject']}' at {e['time']}" for e in items]
                recent_emails_str = ", ".join(summary_list)
            else:
                recent_emails_str = "None"

            email_report = f"Email Telemetry: {count} unread primary emails. Most recent: {recent_emails_str}"
        except Exception as e:
            print(f"[SYSTEM]: Email fetch failed: ({e})")
            email_report = "Email Telemetry: ERROR (Check connection)"

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
    
    combined_raw_data = f"{weather_report} {sports_report} {email_report} {memory_report}"

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