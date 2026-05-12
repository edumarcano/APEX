# APEX — Automated Personal Environment Xylem

A Python-based personal HUD that delivers a synchronized audio-visual briefing on demand. The idea came from wanting a real-world analog to Jarvis from Iron Man: a system that wakes up, reads the room, and gives you a situational briefing without you having to ask. Along the way it became a practical tool for automating the morning routine of checking weather, sports updates, news headlines, and personal reminders. Out of the box, APEX ships with a 'Nature Specialist' persona that leans into this imagery, but the core engine is built to be a completely blank slate where the name, voice, and attitude are fully configurable.

---

## How It Works

When triggered, APEX runs a series of environment checks before doing anything. If it passes, it pulls live data from whichever sources are enabled in `config.json`, feeds it to Gemini 2.5 Flash via the Google GenAI SDK, and plays back the AI-generated briefing through text-to-speech while displaying a floating HUD in the corner of the screen. If Gemini is unavailable, it falls back to reading the raw data out loud so the briefing never fails. In dev/test mode, the Gemini call is skipped entirely to save API quota and it just reads the raw data instead.

```
scanner.py  →  [Data Connectors (Clients & DB)]  →  brain.py       →  [Output Drivers (Speaker & GUI)]
  (Gate)               (Collection)              (Synthesis)              (Delivery)
```

---

## Features

**Context-aware gating (`scanner.py`)**  
Before any API calls are made, the scanner checks whether you're on your home Wi-Fi (by SSID), whether the machine is plugged in, and whether it's been at least 6 hours since the last run. All three have to pass for a standard run to prevent it from activating on every login or while away from home. However, .env flags can bypass specific checks depending on whether you're testing or showcasing, without disabling the entire gate.

**Live data connectors (`weather_client.py`, `sports_client.py`, `news_client.py`, `gmail_client.py`, `calendar_client.py`)**  
Weather comes from the OpenWeatherMap API. `sports_client.py` pulls two feeds: the next F1 race from the Ergast/Jolpica API, and the next FC Barcelona fixture from the football-data.org API (authenticated via `FOOTBALL_API_KEY`). `news_client.py` fetches one headline each for Artificial Intelligence and Global Events from the GNews API (authenticated via `GNEWS_API_KEY`), with a short sleep between requests to stay inside the free-tier rate limit. Unread Primary inbox emails come from the Gmail API. Calendar data comes from the Google Calendar API as a rolling 48-hour window. Both Google clients share the same OAuth2 flow through `google_auth.py`. Each connector is its own module, so adding a new source is mostly isolated to one new file and a few lines in `main.py`. Every connector can be individually toggled on or off via `config.json`. When a connector is disabled, the API call is skipped entirely and the module is excluded from the briefing.

**Config-driven feature flags and persona (`config.json`, `config.py`)**  
`config.py` reads `config.json` at startup and exposes a boolean for each connector (`FEATURE_WEATHER`, `FEATURE_SPORTS`, `FEATURE_NEWS`, `FEATURE_EMAIL`, `FEATURE_CALENDAR`) plus `SYSTEM_PROMPT`, the string that sets the AI's voice, persona name, and how it addresses the user. If the file is missing or broken, flags default to `False` and `SYSTEM_PROMPT` falls back to a generic placeholder so nothing crashes. `config.json` ships committed with all flags on. It also keeps preferences and secrets separate: toggles and the persona prompt live here (safe to commit), API keys go in `.env` (gitignored).

**AI-generated briefings (`brain.py`)**  
Raw data from all the connectors is passed straight to Gemini 2.5 Flash via the Google GenAI SDK. `brain.py` has no persona baked into it. It pulls `SYSTEM_PROMPT` from `config.py` and prepends it to the request, so the voice is entirely driven by `config.json`. Pipe (`|`) delimiters separate each source in the raw string to keep the model's context clean. If the API call fails for any reason, it catches the exception and falls back to reading the raw data directly so the run never crashes.

**Latency masking with threading (`main.py`)**  
Google GenAI SDK calls take a second or two. Rather than stalling in silence, a filler phrase ("Generating briefing... Please wait...") plays on a separate thread while the model processes. The briefing starts as soon as it's ready.

**Persistent reminders and session logging (`database.py`)**  
A local SQLite database tracks user reminders and run timestamps. Reminders are marked as read after they've been read out so they don't repeat across sessions. The run log is what the scanner queries to enforce the 6-hour cooldown.

**Testing Mode (`TEST_MODE`)**  
For active development. Bypasses the 6-hour cooldown and the Gemini API call, returning a raw data readout instead to preserve API quota. Gmail and Calendar are also skipped regardless of `config.json` to keep personal data out of test runs. The Wi-Fi and power checks still run to keep the environment consistent with production. Skips `database.log_run()` so session history stays clean during testing.

**Showcase Mode (`SHOWCASE_MODE`)**  
Bypasses all hardware and cooldown checks so the system runs anywhere, but keeps the live Gemini call intact so the briefing is real. Gmail and Calendar are skipped here as well regardless of `config.json` to keep personal data out of demos. Like `TEST_MODE`, it also skips `database.log_run()` so running a demo doesn't reset the actual daily cooldown.

**Floating HUD (`gui.py`)**  
A borderless, semi-transparent window built with CustomTkinter that appears in the top-right corner of the screen. It shows the briefing text, live CPU and RAM usage via `psutil`, and a text field for logging new reminders directly into the database.

---

## The Default Configuration (Nature-Themed Tone)

The briefing voice, the AI's name, and how it addresses the user are all set by the `system_prompt` field in `config.json`. Nothing about that is hardcoded. Change the value and the whole personality changes.

The default persona that ships with the project is nature-themed, a deliberate personal choice. Just as xylem tissue carries nutrients through a tree, APEX moves your personal data through its processing layers, a parallel too good to leave at just the name. That imagery is carried over into the briefing voice and is reflected in the tone, and the word choices.

---

## Environment Modes

Both flags are read from `.env` and default to `"false"` if the key is absent. All values are normalized to lowercase at read time, so `True`, `true`, and `TRUE` all work the same way.

| Flag | Wi-Fi + Power | Cooldown | Gemini API | Gmail + Calendar (PII) | Logs Run |
|---|---|---|---|---|---|
| Neither (production) | ✅ enforced | ✅ enforced | ✅ live (w/ fallback) | ✅ enabled | ✅ yes |
| `TEST_MODE=True` | ✅ enforced | ⬜ bypassed | ⬜ bypassed | ⬜ bypassed | ⬜ no |
| `SHOWCASE_MODE=True` | ⬜ bypassed | ⬜ bypassed | ✅ live (w/ fallback) | ⬜ bypassed | ⬜ no |

## Feature Toggles

Individual data connectors can be switched on or off in `config.json` without touching any code. This is useful when you don't hold a particular API key, want to speed up development runs by cutting unused sources, or just don't need a connector for a period of time.

Set any `features` value to `false` to disable that connector. When a connector is off, no API call or authentication attempt is made, the module is excluded from the Gemini context window, and a bypass notice is logged to the terminal.

Two edge cases worth knowing:

- `TEST_MODE` and `SHOWCASE_MODE` always force-bypass Gmail and Calendar regardless of `config.json`. Feature flags are an additional layer of control that only matters in a normal production run.
- If `config.json` is missing or broken, `config.py` logs a warning and defaults every feature flag to `False` and `SYSTEM_PROMPT` to a neutral generic fallback so the system doesn't crash.

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

The project uses a set of custom agent rules in `.cursor/rules/`. A shared global config (`global.mdc`) enforces two rules across every agent: TTS output compatibility and PEP-8 compliance. The roles are:

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

**4. Configure persona and feature toggles (optional)**

`config.json` ships with all five connectors enabled and the default Xylem persona set as the system prompt. Both can be customized without touching any code.

To change the briefing voice, tone, or persona, edit the `system_prompt` field. To disable a connector, set its flag to `false`:

```json
{
  "features": {
    "weather": true,
    "sports": false,
    "news": true,
    "email": false,
    "calendar": false
  },
  "system_prompt": "You are APEX. Deliver a sharp, neutral briefing in under 75 words. No emojis or markdown."
}
```

This is also the right way to handle a missing API key. If you skip the `FOOTBALL_API_KEY` setup, set `"sports": false` here instead of getting a fetch error every run. The briefing will still generate with whatever data is enabled.

`config.py` validates both the `features` object and the `system_prompt` string at startup. If either is missing or malformed, it falls back to safe defaults and logs a warning rather than crashing.

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
├── config.py        # Feature flag and system prompt loader with validation
├── config.json      # Persona prompt and per-connector on/off toggles (user preferences, committed)
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

A few things that aren't obvious just from reading the code:

- **Why split `.env` and `config.json` instead of putting everything in one place?** `.env` is for secrets: API keys, OAuth tokens, anything you'd never commit to a public repo. `config.json` is for preferences: which features to run, the persona prompt, what behavior to opt in or out of. Keeping them separate means the defaults are visible in version control (`config.json` is committed), collaborators can clone the repo and immediately see the expected shape of the config, and `.env.example` stays focused on secrets without getting cluttered with toggles. It also means you can change the persona or a feature flag without touching anything near your credentials.

- **Why Gemini over a template?** Templated output gets repetitive fast and requires manual updates whenever a data source changes format. Passing raw strings to the model and letting it figure out the sentence structure turned out to be simpler and more flexible.

- **Why pyttsx3 over a cloud TTS?** Fully offline, no API key, no latency. For a local morning tool that tradeoff made sense as a starting point, but the robotic voice is a known limitation. Switching to a cloud TTS (ElevenLabs, Google Cloud TTS, etc.) for a more natural-sounding voice is planned.

- **Why SQLite over a flat file?** The reminder feature needs read/write with state (marking items as read). SQLite handles that cleanly without pulling in anything external.

- **Why an offline fallback instead of a secondary API?** The original plan was to route failed Gemini calls to an OpenAI or Anthropic fallback. But developer API credits expire after 12 months, and paying to fund a secondary account that rarely triggers isn't worth it for a personal tool. Just reading the raw data out loud during an outage gets to 100% uptime at zero cost.

- **Logging conventions.** Every module prefixes its terminal output with a bracketed tag: `[BRAIN]`, `[SCANNER]`, `[SPEAKER]`, `[GUI]`, `[WEATHER]`, `[SPORTS]`, `[NEWS]`, `[GMAIL]`, `[CALENDAR]`, `[SYSTEM]`. It makes it easy to tell which module produced a given line when watching a full run scroll past.
