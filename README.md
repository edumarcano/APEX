# APEX: Automated Personal Environment Xylem

A Python-based personal HUD that delivers a synchronized audio-visual briefing on demand. The idea came from wanting a real-world analog to Jarvis from Iron Man: a system that wakes up, reads the room, and gives you a situational briefing without you having to ask. Along the way it became a practical tool for automating the morning routine of checking weather, sports updates, news headlines, and personal reminders. Out of the box, APEX ships with a nature-themed persona that leans into this imagery, but the core engine is built to be a completely blank slate where the name, voice, and attitude are fully configurable.

---

## How It Works

`launcher.py` is the entry point for a full local session. It starts uvicorn and `http.server` as parallel child processes, waits for both to bind their ports, then opens the frontend in a kiosk window using the first Chromium browser binary it finds. `atexit` hooks and signal handlers bring both processes down on exit.

With both servers up, `api.py` listens on `127.0.0.1:8000`. A `POST` to `/api/v1/trigger` kicks off a four-stage pipeline:

1. **Gate** — `scanner.py` checks the environment before anything else: home Wi-Fi by SSID, wall power, and a 6-hour cooldown since the last run. If any check fails, the request is rejected with a `403` and nothing runs.
2. **Collection** — each enabled data connector fetches its feed in sequence: weather, sports, news, email, calendar, and pending reminders from the local database. Disabled connectors are skipped with no API call made.
3. **Synthesis** — the raw outputs are joined into a single pipe-delimited string and passed to Gemini 2.5 Flash via the Google GenAI SDK. `brain.py` prepends the persona prompt from `config.json` and returns the generated briefing text. A filler phrase plays on a background thread while the model processes to avoid dead air. If the Gemini call fails for any reason, the raw data string is read out directly so the run never crashes.
4. **Output** — `speaker.py` plays the final briefing through the TTS fallback chain. The endpoint also returns the briefing text and a telemetry object as JSON, which the web HUD reads to fill each module slot on the page.

In `TEST_MODE`, the Gemini call and Gmail and Calendar connectors are skipped to save API quota during development. `SHOWCASE_MODE` keeps Gemini live but bypasses the hardware checks and skips Gmail and Calendar so the system runs anywhere.

```
launcher.py  →  [uvicorn (port 8000) + http.server (port 5500)]  →  Browser (kiosk window)
api.py  →  scanner.py  →  [Data Connectors (Clients & DB)]  →  brain.py  →  speaker.py
(Entry)      (Gate)              (Collection)               (Synthesis)   (Delivery)
```

---

## Features

**Context-aware gating (`scanner.py`)**  
Before any API calls are made, the scanner checks whether you're on your home Wi-Fi (by SSID), whether the machine is plugged in, and whether it's been at least 6 hours since the last run. All three have to pass for a standard run to prevent it from activating on every login or while away from home. However, .env flags can bypass specific checks depending on whether you're testing or showcasing, without disabling the entire gate.

**Live data connectors (`weather_client.py`, `sports_client.py`, `news_client.py`, `gmail_client.py`, `calendar_client.py`)**  
Weather comes from the OpenWeatherMap API. `sports_client.py` pulls two feeds: the next F1 race from the Ergast/Jolpica API, and the next FC Barcelona fixture from the football-data.org API (authenticated via `FOOTBALL_API_KEY`). `news_client.py` fetches one headline each for Artificial Intelligence and Global Events from the GNews API (authenticated via `GNEWS_API_KEY`), with a short sleep between requests to stay inside the free-tier rate limit. Unread Primary inbox emails come from the Gmail API. Calendar data comes from the Google Calendar API as a rolling 48-hour window. Both Google clients share the same OAuth2 flow through `google_auth.py`. Each connector is its own module, so adding a new source is mostly isolated to one new file and a few lines in `main.py`. Every connector can be individually toggled on or off via `config.json`. When a connector is disabled, the API call is skipped entirely and the module is excluded from the briefing.

**Config-driven feature flags and persona (`config.json`, `config.py`)**  
`config.py` reads `config.json` at startup and exposes a boolean for each connector (`FEATURE_WEATHER`, `FEATURE_SPORTS`, `FEATURE_NEWS`, `FEATURE_EMAIL`, `FEATURE_CALENDAR`), `SYSTEM_PROMPT`, and three TTS constants: `PRIMARY_TTS`, `GOOGLE_VOICE_ID`, and `INWORLD_VOICE_ID`. If the file is missing or broken, flags default to `False`, `SYSTEM_PROMPT` falls back to a generic placeholder, and `PRIMARY_TTS` defaults to `"pyttsx3"` so nothing crashes. `config.json` ships committed with all flags on and Google Cloud TTS configured as the active engine. It also keeps preferences and secrets separate: toggles, the persona prompt, and TTS voice settings live here (safe to commit), API keys go in `.env` (gitignored).

**AI-generated briefings (`brain.py`)**  
Raw data from all the connectors is passed straight to Gemini 2.5 Flash via the Google GenAI SDK. `brain.py` has no persona baked into it. It pulls `SYSTEM_PROMPT` from `config.py` and prepends it to the request, so the voice is entirely driven by `config.json`. Pipe (`|`) delimiters separate each source in the raw string to keep the model's context clean. If the API call fails for any reason, it catches the exception and falls back to reading the raw data directly so the run never crashes.

**Latency masking with threading (`main.py`) — Legacy/Maintenance**  
Google GenAI SDK calls take a second or two. Rather than stalling in silence, a filler phrase ("Generating briefing... Please wait...") plays on a separate thread while the model processes. The briefing starts as soon as it's ready. This logic is also present in the `api.py` trigger endpoint, which is now the active execution path.

**Persistent reminders and session logging (`database.py`)**  
A local SQLite database tracks user reminders and run timestamps. Reminders are marked as read after they've been read out so they don't repeat across sessions. The run log is what the scanner queries to enforce the 6-hour cooldown.

**Testing Mode (`TEST_MODE`)**  
For active development. Bypasses the 6-hour cooldown and the Gemini API call, returning a raw data readout instead to preserve API quota. Gmail and Calendar are also skipped regardless of `config.json` to keep personal data out of test runs. The Wi-Fi and power checks still run to keep the environment consistent with production. Skips `database.log_run()` so session history stays clean during testing.

**Showcase Mode (`SHOWCASE_MODE`)**  
Bypasses all hardware and cooldown checks so the system runs anywhere, but keeps the live Gemini call intact so the briefing is real. Gmail and Calendar are skipped here as well regardless of `config.json` to keep personal data out of demos. Like `TEST_MODE`, it also skips `database.log_run()` so running a demo doesn't reset the actual daily cooldown.

**Web HUD (`index.html`, `style.css`, `app.js`)**  
Three static files served from the project root. On page load, `app.js` fires a `POST` to `/api/v1/trigger` and fills six module slots from the `telemetry` response: weather, sports, news, email, calendar, and reminders. The center panel shows the briefing text with a looping pulse. The header toggles between `SYSTEM ONLINE` and `SYSTEM OFFLINE` based on whether the request came back clean. Layout is a three-column CSS Grid bento that collapses to a single column below 900px. No build step, no framework.

**Floating HUD (`gui.py`) — Legacy/Maintenance**  
A borderless, semi-transparent window built with CustomTkinter that appears in the top-right corner of the screen. It shows the briefing text, live CPU and RAM usage via `psutil`, and a text field for logging new reminders directly into the database. The HUD is launched by `main.py` and is not currently wired into the `api.py` execution path.

**Text-to-speech engine (`speaker.py`)**  
Three engines in a fallback chain. Google Cloud TTS is the primary path: text goes to the Cloud TTS API and the returned MP3 bytes are played directly from memory via `pygame.mixer` with no disk writes. `SDL_VIDEODRIVER=dummy` is set at import time so pygame doesn't crash if there's no display attached. If Google fails or isn't configured, Inworld AI is tried next via its REST API. If both cloud paths are down, `pyttsx3` runs locally with no network dependency. The active engine is set by `primary_tts` in `config.json`. `"google"` tries Google first, then Inworld, then pyttsx3. `"inworld"` reverses that order. `"pyttsx3"` skips cloud entirely.

---

## The Default Configuration (Nature-Themed Tone)

The briefing voice, the AI's name, and how it addresses the user are all set by the `system_prompt` field in `config.json`. Nothing about that is hardcoded. Change the value and the whole personality changes.

The default persona is a deliberate personal choice. Just as xylem tissue carries nutrients through a tree, APEX moves your personal data through its processing layers, a parallel too good to leave at just the name. That imagery is carried over into the briefing voice and is reflected in the tone, and the word choices.

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
| GUI | Web HUD (`index.html`, `style.css`, `app.js`) · active. `gui.py` via CustomTkinter · legacy/maintenance |
| Database | SQLite3 |
| TTS | Google Cloud TTS (primary), Inworld AI (secondary, inactive by default), pyttsx3 (offline fallback) |
| Key Libraries | `psutil`, `requests`, `python-dotenv`, `google-api-python-client`, `google-cloud-texttospeech`, `pygame-ce` |

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

`.env.example` contains all required keys with descriptive placeholders and comments explaining each group. The `.env` file is excluded from version control. Two keys are worth calling out: `GOOGLE_APPLICATION_CREDENTIALS` takes the **absolute file path** to your `service_account.json` file, not the contents of the file. `INWORLD_API_KEY` needs to be a pre-Base64-encoded `client_id:client_secret` pair, exactly as formatted in the Inworld AI console.

`APEX_ALLOWED_ORIGINS` is an optional comma-separated list of origins allowed to make cross-origin requests to the API. If it's not set, `api.py` defaults to `http://127.0.0.1:8000`, `http://localhost:8000`, `http://127.0.0.1:5500`, and `http://localhost:5500`. If you're serving the web HUD from a different port, set this key. Note that a custom value replaces the defaults entirely rather than adding to them.

`CUSTOM_BROWSER_PATH` points `launcher.py` at a specific browser executable for the kiosk window. If you use Vivaldi, Brave, or any other Chromium-based browser that is not Chrome or Edge, set the full path here (e.g., `C:\Users\you\AppData\Local\Vivaldi\Application\vivaldi.exe`). It gets checked first. If it is not set, `launcher.py` looks for Chrome then Edge under the default `PROGRAMFILES` paths.

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
  "tts_settings": {
    "primary_tts": "google",
    "google_voice_id": "en-US-Chirp3-HD-Gacrux",
    "inworld_voice_id": ""
  },
  "system_prompt": "You are APEX. Deliver a sharp, neutral briefing in under 75 words. No emojis or markdown."
}
```

`primary_tts` accepts `"google"`, `"inworld"`, or `"pyttsx3"`. Leave `google_voice_id` or `inworld_voice_id` blank to skip that engine regardless of the `primary_tts` setting.

This is also the right way to handle a missing API key. If you skip the `FOOTBALL_API_KEY` setup, set `"sports": false` here instead of getting a fetch error every run. The briefing will still generate with whatever data is enabled.

`config.py` validates both the `features` object and the `system_prompt` string at startup. If either is missing or malformed, it falls back to safe defaults and logs a warning rather than crashing.

**5. Set up Google API credentials**

- Go to the Google Cloud Console.
- Enable both the Gmail API and the Google Calendar API for your project.
- Create an OAuth client ID for a desktop application and download it as `credentials.json`.
- Place `credentials.json` in the project root directory.
- If you change API scopes later, delete `token.json` and re-authenticate to get a fresh token.

**6. Set up Google Cloud TTS credentials**

- Go to the Google Cloud Console.
- Enable the **Cloud Text-to-Speech API** for your project.
- Create a **service account**, grant it the `Cloud Text-to-Speech User` role, and download the JSON key.
- Save the key file as `service_account.json` in the project root (it is gitignored).
- Set `GOOGLE_APPLICATION_CREDENTIALS` in `.env` to the **absolute file path** of that file (e.g., `C:\Users\you\projects\apex\service_account.json`).

**7. (Optional) Configure Inworld AI**

Inworld AI is wired in as a secondary TTS engine but is inactive by default. To enable it:

- Create an Inworld AI account and obtain your `client_id` and `client_secret`.
- Base64-encode the pair (`base64("client_id:client_secret")`) and paste the result as `INWORLD_API_KEY` in `.env`.
- Set `"inworld_voice_id"` in `config.json` to a valid Inworld voice ID.
- Set `"primary_tts"` to `"inworld"` if you want it to be tried before Google.

**8. Run**

The recommended way to start is with the orchestrator:

```bash
python launcher.py
```

This starts uvicorn and `http.server` in the background, waits for both to come up, then opens the frontend in a kiosk window automatically. `Ctrl+C` shuts both down.

To run the processes separately:

**Terminal 1 (API server):**
```bash
python -m uvicorn core.api:app --reload
```

**Terminal 2 (static file server):**
```bash
python -m http.server -d frontend 5500
```

Then open `http://127.0.0.1:5500` in a browser. Both commands are run from the project root. The `-d frontend` flag points the file server directly at the `frontend/` directory, so all assets resolve correctly without navigating into the folder. `app.js` fires the trigger automatically on load.

> **Legacy path:** `legacy/main.py` and `legacy/gui.py` have not had their imports updated to match the new package structure (`core.*`, `clients.*`) and will not run as-is. They are preserved for reference only.

---

## Deployment & Launch

`launch_apex.bat` is in the project root. Double-click it, or run it from a terminal:

```powershell
.\launch_apex.bat
```

It runs `launcher.py` and holds the window open on exit so errors don't disappear before you can read them.

**Creating a Windows Desktop Shortcut**

Right-click `launch_apex.bat` → **Create shortcut**, then drop it on the Desktop. One extra step: right-click the shortcut, open **Properties**, and set the **Start in** field to the full project path (e.g., `C:\Users\you\Documents\APEX`). Without this, `launcher.py` can't resolve its relative paths and the run will fail immediately.

**Why this exists**

The long-term plan is a physical button that cold-starts the whole system without touching a keyboard. This `.bat` file is the software stand-in for that same single-trigger behavior, just from the desktop instead of a hardware input. When that integration gets built, this is what it calls.

---

## API Usage

With both processes running, two endpoints are available:

**Health check**
```
GET http://127.0.0.1:8000/
```
Returns `{"status": "online", "system": "APEX Nexus"}`. Useful for confirming the server came up cleanly before sending a trigger.

**Trigger a briefing**
```
POST http://127.0.0.1:8000/api/v1/trigger
```
Kicks off a full run: scanner gate, data collection, Gemini synthesis, and TTS playback. On success, returns a JSON payload with three fields:

```json
{
  "status": "success",
  "briefing": "...",
  "telemetry": {
    "weather": "...",
    "sports": "...",
    "news": "...",
    "email": "...",
    "calendar": "...",
    "reminders": "..."
  }
}
```

`briefing` is the AI-generated text that was read aloud. `telemetry` is a JSON object with one string field per connector, not the raw pipe-delimited string passed to Gemini internally. The web HUD reads these keys to fill each module slot. If the scanner gate fails (wrong network, no power, or inside the cooldown window), the endpoint returns a `403` with a detail message instead of running.

---

## Project Structure

```
apex/
├── core/
│   ├── api.py           # REST API entry point — FastAPI app + uvicorn server (port 8000)
│   ├── brain.py         # Briefing synthesis via genai.Client and Gemini 2.5 Flash
│   ├── scanner.py       # Environment gate (Wi-Fi, power, cooldown)
│   ├── speaker.py       # TTS fallback chain: Google Cloud TTS → Inworld AI → pyttsx3, MP3 played from memory via pygame
│   ├── database.py      # SQLite session logging and reminder management
│   ├── config.py        # Feature flag and system prompt loader with validation
│   └── __init__.py
├── clients/
│   ├── weather_client.py    # OpenWeatherMap connector
│   ├── sports_client.py     # F1 (Ergast/Jolpica) and FC Barcelona fixture connector (football-data.org)
│   ├── news_client.py       # GNews API connector for AI and Global Events headlines
│   ├── gmail_client.py      # Gmail API v1 extraction and timestamp parsing
│   ├── calendar_client.py   # Google Calendar 48-hour schedule extractor
│   ├── google_auth.py       # Centralized OAuth2 utility for Google APIs
│   └── __init__.py
├── frontend/
│   ├── index.html       # Web HUD entry point — Bento-grid shell with named data slots
│   ├── style.css        # HUD theme — monochrome dark, CSS Grid layout, animation keyframes
│   └── app.js           # HUD client — fetch trigger, telemetry injection, status toggling
├── legacy/
│   ├── main.py          # Direct script entry point (Legacy/Maintenance)
│   └── gui.py           # CustomTkinter HUD display (Legacy/Maintenance)
├── launcher.py          # Master orchestrator — starts uvicorn and http.server in parallel, opens browser kiosk
├── config.json          # Persona prompt, feature toggles, and TTS engine settings (user preferences, committed)
├── apex_memory.db       # Auto-generated on first run
├── credentials.json     # Google Cloud OAuth client ID for Gmail/Calendar (BYOK - not committed)
├── service_account.json # Google Cloud TTS service account key (BYOK - not committed)
├── token.json           # Auto-generated user access token (not committed)
├── .env                 # Local environment variables (not committed)
└── .env.example         # Environment variable template with placeholder values
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

- **Why this specific TTS setup?** Inworld AI was the original primary engine. It was integrated under the assumption that it had a usable free tier for REST API access. It doesn't. After implementation it became clear that Inworld runs on a finite promotional credit model (a $1.00 grant that debits per synthesis request), which isn't practical for a personal tool. Google Cloud TTS replaced it as the primary engine because its 1-million-character monthly free tier is actually sustainable for a daily briefing tool long-term. The Inworld code in `speaker.py` was left in on purpose rather than deleted. When its credits eventually run out and the API starts returning HTTP 403s, it gives a real test of whether the fallback chain holds. If `pyttsx3` takes over cleanly with no crash, the circuit breaker logic is proven. It's a live integration test that costs nothing to run.

- **Why SQLite over a flat file?** The reminder feature needs read/write with state (marking items as read). SQLite handles that cleanly without pulling in anything external.

- **Why an offline fallback instead of a secondary LLM?** For the briefing synthesis layer specifically, the original plan was to route failed Gemini calls to an OpenAI or Anthropic fallback. But developer API credits expire after 12 months, and paying to fund a secondary account that rarely triggers isn't worth it for a personal tool. Just reading the raw data out loud during an outage gets to 100% uptime at zero cost. (The TTS layer is covered in the note above.)

- **Logging conventions.** Every module prefixes its terminal output with a bracketed tag: `[BRAIN]`, `[SCANNER]`, `[SPEAKER]`, `[GUI]`, `[WEATHER]`, `[SPORTS]`, `[NEWS]`, `[GMAIL]`, `[CALENDAR]`, `[SYSTEM]`. It makes it easy to tell which module produced a given line when watching a full run scroll past.

- **Environment isolation.** `launcher.py` intentionally gives each child process a different environment. Uvicorn gets the full environment, including all `.env` keys. The static file server and browser each get a stripped copy with only `PATH`, `SYSTEMROOT`, `TEMP`, `TMP`, and `PYTHONPATH`. API keys never reach the browser process. There is no reason they should.
