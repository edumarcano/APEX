# APEX — Automated Personal Environment Xylem

A Python-based personal HUD that delivers a synchronized audio-visual briefing on demand. The idea came from wanting a real-world analog to Jarvis from Iron Man: a system that wakes up, reads the room, and gives you a situational briefing without you having to ask. The name and personality of the system come from a separate set of personal preferences around nature imagery, which is why it feels more like a specialist briefing you than a butler waiting on you. Along the way it became a practical tool for automating the morning routine of checking weather, sports updates, news headlines, and personal reminders.

---

## How It Works

When triggered, APEX runs a series of environment checks before doing anything. If it passes, it pulls live data from whichever sources are enabled in `config.json`, feeds it to Gemini 2.5 Flash via the Google GenAI SDK, and plays back the AI-generated briefing through text-to-speech while displaying a floating HUD in the corner of the screen. If Gemini is unavailable, it falls back to reading the raw data out loud so the briefing never fails. In dev/test mode, the Gemini call is skipped entirely to save API quota and it just reads the raw data instead.

```
scanner.py  →  [Data Roots (Clients & DB)]  →  brain.py       →  [Output Drivers (Speaker & GUI)]
  (Gate)             (Collection)            (Synthesis)              (Delivery)
```

---

## Features

**Context-aware gating (`scanner.py`)**  
Before any API calls are made, the scanner checks whether you're on your home Wi-Fi (by SSID), whether the machine is plugged in, and whether it's been at least 6 hours since the last run. All three have to pass for a standard run to prevent it from activating on every login or while away from home. However, .env flags can bypass specific checks depending on whether you're testing or showcasing, without disabling the entire gate.

**Live data connectors (`weather_client.py`, `sports_client.py`, `news_client.py`, `gmail_client.py`, `calendar_client.py`)**  
Weather comes from the OpenWeatherMap API. `sports_client.py` pulls two feeds: the next F1 race from the Ergast/Jolpica API, and the next FC Barcelona fixture from the football-data.org API (authenticated via `FOOTBALL_API_KEY`). `news_client.py` fetches one headline each for Artificial Intelligence and Global Events from the GNews API (authenticated via `GNEWS_API_KEY`), with a short sleep between requests to stay inside the free-tier rate limit. Unread Primary inbox emails come from the Gmail API. Calendar data comes from the Google Calendar API as a rolling 48-hour window. Both Google clients share the same OAuth2 flow through `google_auth.py`. Each connector is its own module, so adding a new source is mostly isolated to one new file and a few lines in `main.py`. Every connector can be individually toggled on or off via `config.json`. When a connector is disabled, the API call is skipped entirely and the module is excluded from the briefing.

**Config-driven feature flags (`config.json`, `config.py`)**  
`config.py` reads `config.json` at startup and exposes a boolean constant for each connector (`FEATURE_WEATHER`, `FEATURE_SPORTS`, `FEATURE_NEWS`, `FEATURE_EMAIL`, `FEATURE_CALENDAR`). If the file is missing, unreadable, or malformed, everything defaults to `False` and a warning is logged so the run doesn't crash. `config.json` is committed to the repo with all flags set to `true`, making the defaults work out of the box. This is also where the project draws a hard line between user preferences and secrets: `config.json` holds non-sensitive settings (safe to commit), while API keys stay in `.env` (gitignored).

**AI-generated briefings (`brain.py`)**  
Raw data strings from all the connectors are passed directly to Gemini 2.5 Flash via the Google GenAI SDK. Pipe (`|`) delimiters separate each source in the raw string to keep context clean for the model. It turns everything into a briefing under 75 words with a consistent voice and tone, no templates and no manual string formatting. If the API call fails, it catches the exception and falls back to reading the raw data directly, so the run never crashes.

**Latency masking with threading (`main.py`)**  
Google GenAI SDK calls take a second or two. Rather than stalling in silence, a filler phrase ("Analyzing telemetry... Stand by...") plays on a separate thread while the model processes. The briefing starts as soon as it's ready.

**Persistent reminders and session logging (`database.py`)**  
A local SQLite database tracks user reminders and run timestamps. Reminders are marked as read after being surfaced so they don't repeat across sessions. The run log is what the scanner queries to enforce the 6-hour cooldown.

**Testing Mode (`TEST_MODE`)**  
For active development. Bypasses the 6-hour cooldown and the Gemini API call, returning a raw data readout instead to preserve API quota. Gmail and Calendar are also skipped regardless of `config.json` to keep personal data out of test runs. The Wi-Fi and power checks still run to keep the environment consistent with production. Skips `database.log_run()` so session history stays clean during testing.

**Showcase Mode (`SHOWCASE_MODE`)**  
Bypasses all hardware and cooldown checks so the system runs anywhere, but keeps the live Gemini call intact so the briefing is real. Gmail and Calendar are skipped here as well regardless of `config.json` to keep personal data out of demos. Like `TEST_MODE`, it also skips `database.log_run()` so running a demo doesn't reset the actual daily cooldown.

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

## Feature Toggles

Individual data connectors can be switched on or off in `config.json` without touching any code. This is useful when you don't hold a particular API key, want to speed up development runs by cutting unused sources, or just don't need a connector for a period of time.

```json
{
  "features": {
    "weather": true,
    "sports": true,
    "news": true,
    "email": true,
    "calendar": true
  }
}
```

Set any value to `false` to disable that connector. When a connector is off, no API call or authentication attempt is made, the module is excluded from the Gemini context window, while a bypass notice is logged to the terminal.

A few things worth knowing about the priority order:

- `TEST_MODE` and `SHOWCASE_MODE` always force-bypass Gmail and Calendar regardless of `config.json`. Feature flags are an additional layer of control that only matters in a normal production run.
- If `config.json` is missing or broken, `config.py` logs a warning and defaults every flag to `False` so the system doesn't crash, it just runs with everything disabled until you fix the file.

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

### AI-Augmented Development

The project uses a set of custom agent rules in `.cursor/rules/`. A shared global config (`global.mdc`) pins the two non-negotiables across every agent, TTS output compatibility and PEP-8 compliance. Five roles divide the work:

- **Auditor** — security vulnerabilities, edge cases, and PEP-8 violations.
- **Analyst** — codebase exploration, tracing data flow, and answering questions about how things work.
- **Builder** — structural scaffolding and imports, core logic left blank for manual implementation.
- **Mechanic** — targeted syntax fixes and boilerplate generation.
- **Communicator** — documentation synthesis, README updates, and change summarization for architectural review.

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
```

**3. Configure environment variables**

Copy the included template and fill in your values:

macOS / Linux:
```bash
cp .env.example .env
```

Windows:
```powershell
copy .env.example .env
```

`.env.example` contains all required keys with descriptive placeholders and comments explaining each group. The `.env` file is excluded from version control.

**4. Configure feature toggles (optional)**

`config.json` ships with all five connectors enabled. If you don't have a particular API key or just want to cut a connector out of your runs, set its flag to `false`:

```json
{
  "features": {
    "weather": true,
    "sports": false,
    "news": true,
    "email": false,
    "calendar": false
  }
}
```

This is the right place to handle missing API keys gracefully. For example, if you skip the `FOOTBALL_API_KEY` setup, just set `"sports": false` here instead of getting a fetch error every run. The briefing will still generate with whatever data is enabled.

**5. Set up Google API credentials**

- Go to the Google Cloud Console.
- Enable both the Gmail API and the Google Calendar API for your project.
- Create an OAuth client ID for a desktop application and download it as `credentials.json`.
- Place `credentials.json` in the project root directory.
- If you change API scopes later, delete `token.json` and re-authenticate to get a fresh token.

**6. Run**
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
├── sports_client.py   # F1 (Ergast/Jolpica) and FC Barcelona fixture connector (football-data.org)
├── news_client.py     # GNews API connector for AI and Global Events headlines
├── gmail_client.py    # Gmail API v1 extraction and timestamp parsing
├── calendar_client.py # Google Calendar 48-hour schedule extractor
├── google_auth.py     # Centralized OAuth2 utility for Google APIs
├── speaker.py       # Text-to-speech output via pyttsx3
├── gui.py           # CustomTkinter HUD display
├── database.py      # SQLite session logging and reminder management
├── config.py        # Feature flag loader and validation
├── config.json      # Per-connector on/off toggles (user preferences, committed)
├── apex_memory.db   # Auto-generated on first run
├── credentials.json # Google Cloud OAuth client ID (BYOK - not committed)
├── token.json       # Auto-generated user access token (not committed)
├── .env             # Local environment variables (not committed)
└── .env.example     # Environment variable template with placeholder values
```

---

## Roadmap

Development is tracked via GitHub Issues and milestones. For the latest on what's planned, in progress, or recently shipped, check the live project board:

**[👉 View Live Development Roadmap](https://github.com/edumarcano/apex/projects)**

---

## Notes on Design

Some decisions that might not be obvious from the code alone:

- **Why split `.env` and `config.json` instead of putting everything in one place?** `.env` is for secrets: API keys, OAuth tokens, anything you'd never commit to a public repo. `config.json` is for preferences: which features to run, what behavior to opt in or out of. Keeping them separate means the defaults are visible in version control (`config.json` is committed), collaborators can clone the repo and immediately see the expected shape of the config, and `.env.example` stays focused on secrets without getting cluttered with toggles. It also means you can change a feature flag without touching anything near your credentials.

- **Why Gemini over a template?** Templated output gets repetitive fast and requires manual updates whenever a data source changes format. Passing raw strings to the model and letting it figure out the sentence structure turned out to be simpler and more flexible.
- **Why pyttsx3 over a cloud TTS?** Fully offline, no API key, no latency. For a local morning tool that tradeoff made sense as a starting point, but the robotic voice is a known limitation. Switching to a cloud TTS (ElevenLabs, Google Cloud TTS, etc.) for a more natural-sounding voice is planned.
- **Why SQLite over a flat file?** The reminder feature needs read/write with state (marking items as read). SQLite handles that cleanly without pulling in anything external.
- **Why an offline fallback instead of a secondary API?** The original plan was to route failed Gemini calls to an OpenAI or Anthropic fallback. But developer API credits expire after 12 months, and paying to fund a secondary account that rarely triggers isn't worth it for a personal tool. Just reading the raw data out loud during an outage gets to 100% uptime at zero cost.