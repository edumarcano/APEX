import os
import requests
from dotenv import load_dotenv

load_dotenv()


def fetch_weather_data():
    """
    Connects to the OpenWeatherMap API to retrieve current weather data.

    Returns:
        str: A formatted string containing the temperature and weather condition, 
             or an error message if the connection fails.
    """    
    api_key = os.getenv("OPENWEATHER_API_KEY")
    location = os.getenv("TARGET_LOCATION")
    
    if not api_key or not location:
        return "Weather API offline: Missing API key or location."

    url = f"http://api.openweathermap.org/data/2.5/weather?q={location}&appid={api_key}&units=imperial"
    
    try:
        response = requests.get(url)
        data = response.json()
        
        if response.status_code == 200:
            temp = round(data["main"]["temp"])
            condition = data["weather"][0]["description"]
            
            return f"Current temperature is {temp} degrees with {condition}."
        else:
            return f"Weather API error: {data.get('message', 'Unknown error')}."
            
    except Exception as e:
        return "Failed to connect to Weather API."

if __name__ == "__main__":
    print("[WEATHER]: Weather client diagnostics")
    print(f"[WEATHER]: {fetch_weather_data()}")