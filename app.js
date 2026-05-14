const APEX_TRIGGER_URL = "http://127.0.0.1:8000/api/v1/trigger";

const TELEMETRY_KEYS = [
  "weather",
  "sports",
  "news",
  "email",
  "calendar",
  "reminders",
];

const STATUS_ONLINE = "SYSTEM ONLINE";
const STATUS_OFFLINE = "SYSTEM OFFLINE";

const OFFLINE_STATUS_CLASS = "hud-header__status--offline";

function setDataSlot(id, value) {
  const el = document.getElementById(id);
  if (!el) return;
  const text = value === null || value === undefined ? "" : String(value);
  el.textContent = text;
}

function injectTelemetry(telemetry) {
  if (!telemetry || typeof telemetry !== "object") {
    TELEMETRY_KEYS.forEach((key) => setDataSlot(`data-${key}`, ""));
    return;
  }

  /** @type {Record<string, unknown>} */
  const telemetryData = telemetry;

  TELEMETRY_KEYS.forEach((key) => {
    setDataSlot(`data-${key}`, telemetryData[key]);
  });
}

function injectBriefing(briefing) {
  setDataSlot("data-briefing", briefing);
}

function setSystemStatus(message, online) {
  const statusEl = document.querySelector(".hud-header__status");
  if (!statusEl) return;
  statusEl.textContent = message;
  statusEl.classList.toggle(OFFLINE_STATUS_CLASS, !online);
}

function clearHudSlots() {
  injectTelemetry(null);
  injectBriefing("");
}

async function fetchApexData() {
  try {
    const response = await fetch(APEX_TRIGGER_URL, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({}),
    });

    if (!response.ok) {
      clearHudSlots();
      setSystemStatus(STATUS_OFFLINE, false);
      return;
    }

    /** @type {{ telemetry?: unknown; briefing?: unknown }} */
    const payload = await response.json();

    injectTelemetry(payload.telemetry);
    injectBriefing(payload.briefing);
    setSystemStatus(STATUS_ONLINE, true);
  } catch {
    clearHudSlots();
    setSystemStatus(STATUS_OFFLINE, false);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  void fetchApexData();
});
