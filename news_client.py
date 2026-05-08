import os
import requests
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

    #TODO: Implement try-except block and API request logic for topics

    return '[NEWS]: Awaiting API logic'

if __name__ == "__main__":
    print('Initializing News Service Test...')
    test_data = fetch_news_data()
    print(f'Test Data: {test_data}')