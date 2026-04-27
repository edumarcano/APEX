import os
import requests
from dotenv import load_dotenv

load_dotenv()


def fetch_weather_root():
    """
    Connects to the OpenWeatherMap API to retrieve current weather data.

    Returns:
        str: A formatted string containing the temperature and weather condition, 
             or an error message if the connection fails.
    """    
    api_key = os.getenv("OPENWEATHER_API_KEY")
    location = os.getenv("TARGET_LOCATION")
    
    if not api_key or not location:
        return "Weather Root offline: Missing environment variables."

    url = f"http://api.openweathermap.org/data/2.5/weather?q={location}&appid={api_key}&units=imperial"
    
    try:
        response = requests.get(url)
        data = response.json()
        
        if response.status_code == 200:
            temp = round(data["main"]["temp"])
            condition = data["weather"][0]["description"]
            
            return f"Environment stabilized at {temp} degrees with {condition}."
        else:
            return f"Weather Root anomaly: {data.get('message', 'Unknown error')}."
            
    except Exception as e:
        return "Weather Root failed to establish connection."

if __name__ == "__main__":
    print(f"--- APEX Root Diagnostics ---")
    print(fetch_weather_root())