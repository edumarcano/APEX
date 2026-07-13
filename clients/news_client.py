"""GNews connector with typed briefing results."""

from __future__ import annotations

import os
import time
from typing import Any

import requests
from dotenv import load_dotenv

from core.connectors.models import ConnectorResult, utc_now_iso

load_dotenv()
api_key = os.getenv("GNEWS_API_KEY")


def collect_news() -> ConnectorResult:
    """Collect news headlines as a typed connector result."""
    observed_at = utc_now_iso()
    if not api_key:
        return ConnectorResult(
            name="news",
            status="unavailable",
            freshness="none",
            reason_code="missing_credentials",
            observed_at=observed_at,
            display_text="[NEWS]: Offline. Missing API key.",
        )

    topics = ["Artificial Intelligence", "Global Events"]
    headlines: list[dict[str, str]] = []
    formatted_headlines: list[str] = []
    successes = 0
    failures = 0
    invalid_payloads = 0

    for topic in topics:
        time.sleep(1.1)
        try:
            url = (
                f"https://gnews.io/api/v4/search"
                f"?q={topic}&lang=en&max=1&apikey={api_key}"
            )
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("News response root must be an object.")
            articles = data.get("articles") or []
            if not isinstance(articles, list):
                raise ValueError("News articles must be a list.")
            if articles:
                article = articles[0]
                if not isinstance(article, dict):
                    raise ValueError("News article must be an object.")
                headline = str(article.get("title") or "").strip() or "Untitled"
                headlines.append({"topic": topic, "headline": headline})
                formatted_headlines.append(f"[{topic}] {headline}")
                successes += 1
            else:
                formatted_headlines.append(f"[{topic}] No major headlines found.")
                successes += 1
        except requests.exceptions.RequestException:
            print("[NEWS] Error: Failed to fetch headline telemetry for a topic.")
            formatted_headlines.append(f"[{topic}]: Telemetry unavailable.")
            failures += 1
        except (TypeError, ValueError):
            print("[NEWS] Error: Invalid headline telemetry payload for a topic.")
            formatted_headlines.append(f"[{topic}]: Telemetry unavailable.")
            failures += 1
            invalid_payloads += 1

    display = "[NEWS TELEMETRY]\n" + " | ".join(formatted_headlines)
    data: dict[str, Any] = {"headlines": headlines, "topic_count": len(topics)}

    if successes == 0:
        status = "unavailable"
        reason = "invalid_payload" if invalid_payloads == failures else "provider_error"
        freshness = "none"
    elif failures > 0:
        status = "degraded"
        reason = "partial_failure"
        freshness = "live"
    else:
        status = "healthy"
        reason = "ok"
        freshness = "live"

    return ConnectorResult(
        name="news",
        status=status,  # type: ignore[arg-type]
        freshness=freshness,  # type: ignore[arg-type]
        reason_code=reason,
        observed_at=observed_at,
        display_text=display,
        data=data,
    )


def fetch_news_data() -> str:
    """Compatibility façade returning display text for non-briefing callers."""
    return collect_news().display_text


if __name__ == "__main__":
    print("[NEWS] Initializing news service test.")
    fetch_news_data()
    print("[NEWS] News service test completed.")
