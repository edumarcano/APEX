# APEX — Automated Personal Environment Xylem

A Python-based personal HUD that delivers a synchronized audio-visual briefing on demand. The idea came from wanting a real-world analog to Jarvis from Iron Man: a system that wakes up, reads the room, and gives you a situational briefing without you having to ask. The name and personality of the system come from a separate set of personal preferences around nature imagery, which is why it feels more like a specialist briefing you than a butler waiting on you. Along the way it became a practical tool for automating the morning routine of checking weather, sports updates, and personal reminders.

---

## How It Works

When triggered, APEX runs a series of environment checks before doing anything. If it passes, it pulls live data from various sources, feeds it to Gemini 2.5 Flash via the Google GenAI SDK, and plays back the AI-generated briefing through text-to-speech while displaying a floating HUD in the corner of the screen. If Gemini is unavailable, it falls back to reading the raw data out loud so the briefing never fails. In dev/test mode, the Gemini call is skipped entirely to save API quota and it just reads the raw data instead.

```
scanner.py  →  [Data Roots (Clients & DB)]  →  brain.py       →  [Output Drivers (Speaker & GUI)]
  (Gate)             (Collection)            (Synthesis)              (Delivery)
```

---

## Features

**Context-aware gating (`scanner.py`)**  
Before any API calls are made, the scanner checks whether you're on your home Wi-Fi (by SSID), whether the machine is plugged in, and whether it's been at least 6 hours since the last run. All three have to pass for a standard run to prevent it from activating on every login or while away from home. However, .env flags can bypass specific checks depending on whether you're testing or showcasing, without disabling the entire gate.

**Live data connectors (`weather_client.py`, `sports_client.py`, `gmail_client.py`, `calendar_client.py`)**  
Weather comes from the OpenWeatherMap API. F1 race data comes from the Ergast/Jolpica API. Unread Primary inbox emails come from the Gmail API. Calendar data comes from the Google Calendar API as a rolling 48-hour window. Both Google clients go through `google_auth.py` so they share the same OAuth2 flow and token. Each connector is its own module, so adding a new source means writing one new file and a single line in `main.py`.

**AI-generated briefings (`brain.py`)**  
Raw data strings from all the connectors are passed directly to Gemini 2.5 Flash via the Google GenAI SDK. Pipe (`|`) delimiters separate each source in the raw string to keep context clean for the model. It turns everything into a briefing under 40 words with a consistent voice and tone, no templates and no manual string formatting. If the API call fails, it catches the exception and falls back to reading the raw data directly, so the run never crashes.

**Latency masking with threading (`main.py`)**  
Google GenAI SDK calls take a second or two. Rather than stalling in silence, a filler phrase ("Analyzing telemetry... Stand by...") plays on a separate thread while the model processes. The briefing starts as soon as it's ready.

**Persistent reminders and session logging (`database.py`)**  
A local SQLite database tracks user reminders and run timestamps. Reminders are marked as read after being surfaced so they don't repeat across sessions. The run log is what the scanner queries to enforce the 6-hour cooldown.

**Testing Mode (`TEST_MODE`)**  
For active development. Bypasses the 6-hour cooldown and the Gemini API call, returning a raw data readout instead to preserve API quota. Gmail and Calendar are also skipped to keep personal data out of test runs. The Wi-Fi and power checks still run to keep the environment consistent with production. Skips `database.log_run()` so session history stays clean during testing.

**Showcase Mode (`SHOWCASE_MODE`)**  
Bypasses all hardware and cooldown checks so the system runs anywhere, but keeps the live Gemini call intact so the briefing is real. Gmail and Calendar are skipped here as well to keep personal data out of demos. Like `TEST_MODE`, it also skips `database.log_run()` so running a demo doesn't reset the actual daily cooldown.

**Floating HUD (`gui.py`)**  
A borderless, semi-transparent window built with CustomTkinter that appears in the top-right corner of the screen. It shows the briefing text, live CPU and RAM usage via `psutil`, and a text field for logging new reminders directly into the database.

---

## Environment Modes

Both flags are read from `.env` and default to `"false"` if the key is missing entirely, so the system won't crash with an `AttributeError` if either variable is left out of the config. All values are normalized to lowercase at read time, so `True`, `true`, and `TRUE` all work the same way.

| Flag | Wi-Fi + Power | Cooldown | Gemini API | Gmail + Calendar (PII) | Logs Run |
|---|---|---|---|---|---|
| Neither (production) | ✅ enforced | ✅ enforced | ✅ live (w/ fallback) | ✅ enabled | ✅ yes |
| `TEST_MODE=True` | ✅ enforced | ⬜ bypassed | ⬜ bypassed | ⬜ bypassed | ⬜ no |
| `SHOWCASE_MODE=True` | ⬜ bypassed | ⬜ bypassed | ✅ live (w/ fallback) | ⬜ bypassed | ⬜ no |

---

## Tech Stack

| Layer | Tool |
|---|---|
| Language | Python 3.10+ |
| AI Engine | Google GenAI SDK (Gemini 2.5 Flash) |
| GUI | CustomTkinter |
| Database | SQLite3 |
| TTS | pyttsx3 |
| Key Libraries | `psutil`, `requests`, `python-dotenv`, `google-api-python-client` |

---

## Setup

**1. Clone the repo**
```bash
git clone https://github.com/yourusername/apex.git
cd apex
```

**2. Install dependencies**
```bash
pip install -r requirements.txt
pip install google-genai
pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
```

**3. Configure environment variables**

Create a `.env` file in the project root:
```
GEMINI_API_KEY=your_gemini_api_key
OPENWEATHER_API_KEY=your_openweather_api_key
TARGET_LOCATION=your_city_name
HOME_SSID=your_home_wifi_name
TEST_MODE=False
SHOWCASE_MODE=False
```

**4. Set up Google API credentials**

- Go to the Google Cloud Console.
- Enable both the Gmail API and the Google Calendar API for your project.
- Create an OAuth client ID for a desktop application and download it as `credentials.json`.
- Place `credentials.json` in the project root directory.
- If you change API scopes later, delete `token.json` and re-authenticate to get a fresh token.

**5. Run**
```bash
python main.py
```

---

## Project Structure

```
apex/
├── main.py          # Entry point and execution flow
├── scanner.py       # Environment gate (Wi-Fi, power, cooldown)
├── brain.py         # Briefing synthesis via genai.Client and Gemini 2.5 Flash
├── weather_client.py  # OpenWeatherMap connector
├── sports_client.py   # F1 race data connector (Ergast API)
├── gmail_client.py    # Gmail API v1 extraction and timestamp parsing
├── calendar_client.py # Google Calendar 48-hour schedule extractor
├── google_auth.py     # Centralized OAuth2 utility for Google APIs
├── speaker.py       # Text-to-speech output via pyttsx3
├── gui.py           # CustomTkinter HUD display
├── database.py      # SQLite session logging and reminder management
├── apex_memory.db   # Auto-generated on first run
├── credentials.json # Google Cloud OAuth client ID (BYOK - not committed)
├── token.json       # Auto-generated user access token (not committed)
└── .env             # Local environment variables (not committed)
```

---

## Roadmap

Development is tracked via GitHub Issues and milestones. For the latest on what's planned, in progress, or recently shipped, check the live project board:

**[👉 View Live Development Roadmap](https://github.com/yourusername/apex/projects)**

---

## Notes on Design

Some decisions that might not be obvious from the code alone:

- **Why Gemini over a template?** Templated output gets repetitive fast and requires manual updates whenever a data source changes format. Passing raw strings to the model and letting it figure out the sentence structure turned out to be simpler and more flexible.
- **Why pyttsx3 over a cloud TTS?** Fully offline, no API key, no latency. For a local morning tool that tradeoff made sense as a starting point, but the robotic voice is a known limitation. Switching to a cloud TTS (ElevenLabs, Google Cloud TTS, etc.) for a more natural-sounding voice is planned.
- **Why SQLite over a flat file?** The reminder feature needs read/write with state (marking items as read). SQLite handles that cleanly without pulling in anything external.
- **Why an offline fallback instead of a secondary API?** The original plan was to route failed Gemini calls to an OpenAI or Anthropic fallback. But developer API credits expire after 12 months, and paying to fund a secondary account that rarely triggers isn't worth it for a personal tool. Just reading the raw data out loud during an outage gets to 100% uptime at zero cost.