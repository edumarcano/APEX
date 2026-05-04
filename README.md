# APEX — Automated Personal Environment Xylem

A Python-based personal HUD that delivers a synchronized audio-visual briefing on demand. The idea came from wanting a real-world analog to Jarvis from Iron Man: a system that wakes up, reads the room, and gives you a situational briefing without you having to ask. The name and personality of the system come from a separate set of personal preferences around nature imagery, which is why it feels more like a specialist briefing you than a butler waiting on you. Along the way it became a practical tool for automating the morning routine of checking weather, sports updates, and personal reminders.

---

## How It Works

When triggered, APEX runs a series of environment checks before doing anything. If it passes, it pulls live data from a few sources, feeds it to Gemini 2.5 Flash via the Google GenAI SDK, and plays back the AI-generated briefing through text-to-speech while displaying a floating HUD in the corner of the screen. For development and testing, the Gemini call is bypassed and replaced with a mock briefing to preserve API quota.

```
scanner.py  →  weather.py + sports.py + database.py  →  brain.py  →  speaker.py + gui.py
  (gate)              (data collection)                  (synthesis)     (output)
```

---

## Features

**Context-aware gating (`scanner.py`)**  
Before any API calls are made, the scanner checks whether you're on your home Wi-Fi (by SSID), whether the machine is plugged in, and whether it's been at least 6 hours since the last run. All three have to pass for a standard run to prevent it from activating on every login or while away from home. However, .env flags can bypass specific checks depending on whether you're testing or showcasing, without disabling the entire gate.

**Live data connectors (`weather.py`, `sports.py`)**  
Weather comes from the OpenWeatherMap API. F1 race data comes from the Ergast/Jolpica API. Each connector is in its own module, so adding new sources (Google Calendar, GitHub activity, news headlines) means writing one new file and a single line in `main.py`.

**AI-generated briefings (`brain.py`)**  
Raw data strings from the connectors are passed directly to Gemini 2.5 Flash via the Google GenAI SDK, using the `genai.Client` architecture. The model turns everything into a briefing under 40 words with a consistent voice and tone, no templating or string formatting involved. The wording changes based on whatever the data actually says.

**Latency masking with threading (`main.py`)**  
Google GenAI SDK calls take a second or two. Rather than stalling in silence, a filler phrase ("Analyzing telemetry... Stand by...") plays on a separate thread while the model processes. The briefing starts as soon as it's ready.

**Persistent reminders and session logging (`database.py`)**  
A local SQLite database tracks user reminders and run timestamps. Reminders are marked as read after being surfaced so they don't repeat across sessions. The run log is what the scanner queries to enforce the 6-hour cooldown.

**Testing Mode (`TEST_MODE`)**  
Designed for rapid backend and UI development. Bypasses the 6-hour cooldown and the Gemini API call, returning a mock briefing with the live telemetry data instead. The Wi-Fi and power checks still run to keep the environment consistent with production. Skips `database.log_run()` so session history stays clean during testing.

**Showcase Mode (`SHOWCASE_MODE`)**  
Bypasses all hardware and cooldown checks so the system runs in any environment, but keeps the live Gemini API call intact so the briefing is real. Like `TEST_MODE`, it also skips `database.log_run()` so that running a demo doesn't reset the actual daily cooldown.

**Floating HUD (`gui.py`)**  
A borderless, semi-transparent window built with CustomTkinter that appears in the top-right corner of the screen. It shows the briefing text, live CPU and RAM usage via `psutil`, and a text field for logging new reminders directly into the database.

---

## Environment Modes

Both flags are read from `.env` and default to `"false"` if the key is missing entirely, so the system won't crash with an `AttributeError` if either variable is left out of the config. All values are normalized to lowercase at read time, so `True`, `true`, and `TRUE` all work the same way.

| Flag | Wi-Fi + Power | Cooldown | Gemini API | Logs Run |
|---|---|---|---|---|
| Neither (production) | ✅ enforced | ✅ enforced | ✅ live | ✅ yes |
| `TEST_MODE=True` | ✅ enforced | ⬜ bypassed | ⬜ mock | ⬜ no |
| `SHOWCASE_MODE=True` | ⬜ bypassed | ⬜ bypassed | ✅ live | ⬜ no |

---

## Tech Stack

| Layer | Tool |
|---|---|
| Language | Python 3.10+ |
| AI Engine | Google GenAI SDK (Gemini 2.5 Flash) |
| GUI | CustomTkinter |
| Database | SQLite3 |
| TTS | pyttsx3 |
| Key Libraries | `psutil`, `requests`, `python-dotenv` |

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

**4. Run**
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
├── weather.py       # OpenWeatherMap connector
├── sports.py        # F1 race data connector (Ergast API)
├── speaker.py       # Text-to-speech output via pyttsx3
├── gui.py           # CustomTkinter HUD display
├── database.py      # SQLite session logging and reminder management
├── apex_memory.db   # Auto-generated on first run
└── .env             # Local environment variables (not committed)
```

---

## Roadmap

- [ ] Google Calendar integration for daily schedule briefings
- [ ] Live FC Barcelona fixture data to replace the current hardcoded placeholder
- [ ] News headline connector (e.g., NewsAPI)
- [ ] GitHub activity summary (open PRs, recent commits)
- [ ] Startup trigger via Windows Task Scheduler for true login automation
- [ ] Externalize the persona config (name, voice style, briefing tone) into the `.env` file so the system isn't hardcoded to the APEX/Chief identity

---

## Notes on Design

Some decisions that might not be obvious from the code alone:

- **Why Gemini over a template?** Templated output gets repetitive fast and requires manual updates whenever a data source changes format. Passing raw strings to the model and letting it figure out the sentence structure turned out to be simpler and more flexible.
- **Why pyttsx3 over a cloud TTS?** Fully offline, no API key, no latency. For a local morning tool that tradeoff made sense as a starting point, but the robotic voice is a known limitation. Switching to a cloud TTS (ElevenLabs, Google Cloud TTS, etc.) for a more natural-sounding voice is planned.
- **Why SQLite over a flat file?** The reminder feature needs read/write with state (marking items as read). SQLite handles that cleanly without pulling in anything external.