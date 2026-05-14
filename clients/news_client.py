import os
import requests
import time
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GNEWS_API_KEY")


def fetch_news_data():
    """
    Fetches exactly 2 top headlines (AI and Global Events) using the GNews API.
    Returns:
        str: A formatted string containing the news data, or an error message if the connection fails.
    """
    if not api_key:
        return "[NEWS]: Offline. Missing API key."

    topics = ['Artificial Intelligence', 'Global Events']
    formatted_headlines = []

    for topic in topics:
        time.sleep(1.1)
        try:
            url = f"https://gnews.io/api/v4/search?q={topic}&lang=en&max=1&apikey={api_key}"
            response = requests.get(url, timeout=5)
            response.raise_for_status()

            data = response.json()

            if data.get('articles') and len(data['articles']) > 0:
                headline = data['articles'][0]['title']
                formatted_headlines.append(f"[{topic}] {headline}")
            else:
                formatted_headlines.append(f"[{topic}] No major headlines found.")
        except requests.exceptions.RequestException as e:
            print(f"[NEWS]: Error fetching {topic}: {e}")
            formatted_headlines.append(f"[{topic}]: Telemetry unavailable.")

    final_report = '[NEWS TELEMETRY]\n' + ' | '.join(formatted_headlines)

    return final_report

if __name__ == "__main__":
    print("[NEWS]: Initializing news service test...")
    test_data = fetch_news_data()
    print(f"[NEWS]: Test data: {test_data}")