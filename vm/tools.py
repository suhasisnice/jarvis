import os
import urllib.request
import urllib.parse
import json

# What Jarvis is doing right now, e.g. "Checking the weather in Paris, sir." The laptop
# polls GET /status while it waits and speaks this, so he narrates instead of going silent.
ACTIVITY = ""

# Laptop actions asked for this turn. The VM can't touch the laptop, so the laptop runs these
# itself after the reply arrives (legion/actions.py). Only offered on turns that come from the laptop.
ACTIONS = []
LAPTOP = False

def laptop(action: str, target: str = "") -> str:
    """Do something on the user's laptop. action is one of: open_app (target = app name, e.g. "vs code"),
    open_website (target = site or URL), volume (target = percent 0-100), mute, screenshot, lock, sleep,
    play (target = song or video to play right away, e.g. "Loser by Tame Impala"), pause (also resumes), next,
    find (target = words from a file name, optionally "|days" for recently edited, e.g. "resume|7"; it opens the newest match),
    look (see the user's screen; use when they ask about what is on their screen or in a window).
    Before sleep, ask the user to confirm, and call it only after they say yes."""
    ACTIONS.append({"do": action, "target": str(target)})
    return "Done."

def get_weather(location: str) -> str:
    """
    Get the current weather for a named place.

    Args:
        location (str): The name of the location to get weather for.

    Returns:
        str: A TTS-friendly sentence describing the current weather, or an error message if the location is not found.
    """
    global ACTIVITY
    ACTIVITY = f"Checking the weather in {location}, sir."
    # Step 1: Geocode the location
    geocode_url = 'https://geocoding-api.open-meteo.com/v1/search'
    geocode_params = {
        'name': location,
        'count': 1
    }
    geocode_url += '?' + urllib.parse.urlencode(geocode_params)

    req = urllib.request.Request(
        geocode_url,
        headers={'User-Agent': 'jarvis'},
        method='GET'
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            geocode_data = json.loads(response.read().decode('utf-8'))
    except Exception:
        return "I couldn't find that location, sir."

    if not geocode_data.get('results'):
        return "I couldn't find that location, sir."

    location_data = geocode_data['results'][0]
    latitude = location_data['latitude']
    longitude = location_data['longitude']
    name = location_data['name']
    country = location_data['country']

    # Step 2: Get weather forecast
    weather_url = 'https://api.open-meteo.com/v1/forecast'
    weather_params = {
        'latitude': latitude,
        'longitude': longitude,
        'current': 'temperature_2m,weather_code',
        'daily': 'weather_code,temperature_2m_max,temperature_2m_min',
        'timezone': 'auto'
    }
    weather_url += '?' + urllib.parse.urlencode(weather_params)

    req = urllib.request.Request(
        weather_url,
        headers={'User-Agent': 'jarvis'},
        method='GET'
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            weather_data = json.loads(response.read().decode('utf-8'))
    except Exception:
        return "I couldn't get the weather for that location, sir."

    current_temp = int(weather_data['current']['temperature_2m'])
    current_weather_code = weather_data['current']['weather_code']
    daily_max_temp = int(weather_data['daily']['temperature_2m_max'][0])
    daily_min_temp = int(weather_data['daily']['temperature_2m_min'][0])

    weather_code_map = {
        0: 'clear sky',
        1: 'partly cloudy',
        2: 'partly cloudy',
        3: 'partly cloudy',
        45: 'fog',
        48: 'fog',
        51: 'drizzle',
        53: 'drizzle',
        55: 'drizzle',
        56: 'drizzle',
        57: 'drizzle',
        61: 'rain',
        63: 'rain',
        65: 'rain',
        66: 'rain',
        67: 'rain',
        71: 'snow',
        73: 'snow',
        75: 'snow',
        77: 'snow',
        80: 'rain showers',
        81: 'rain showers',
        82: 'rain showers',
        85: 'snow showers',
        86: 'snow showers',
        95: 'thunderstorm',
        96: 'thunderstorm',
        99: 'thunderstorm'
    }

    current_weather = weather_code_map.get(current_weather_code, 'unclear conditions')

    return f'In {name}, {country} it is currently {current_temp} degrees and {current_weather}, with a high of {daily_max_temp} and a low of {daily_min_temp} today.'

def web_search(query: str) -> str:
    """
    Search the web for current information: news, recent events, who currently
    holds an office, prices, or any fact that may have changed since your
    training. Use this whenever the user asks about something current or you are
    unsure, instead of answering from memory.

    Args:
        query (str): What to search for.

    Returns:
        str: A short, spoken-friendly summary of what the web says.
    """
    global ACTIVITY
    # Short queries read naturally aloud; long ones would be cut mid-phrase, so stay generic.
    ACTIVITY = (f"Searching the web for {query}, sir." if len(query.split()) <= 8
                else "Searching the web, sir.")
    key = os.getenv('TAVILY_API_KEY')
    if not key:
        return "I can't search the web yet, sir — no search key is configured."

    body = json.dumps({
        'query': query,
        'max_results': 5,
        # advanced: one reconciled answer instead of a summary of sites that disagree
        # (basic gave gold at 13,888 / 14,395 / 14,838 from three sites). Costs 2 credits.
        'search_depth': 'advanced',
        'include_answer': 'advanced',
    }).encode('utf-8')
    req = urllib.request.Request(
        'https://api.tavily.com/search',
        data=body,
        method='POST',
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {key}',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
    except Exception:
        return "My web search failed just now, sir."

    # Tavily returns a synthesised 'answer' when include_answer is set; prefer it.
    if data.get('answer'):
        return data['answer']
    results = data.get('results', [])
    if not results:
        return "I found nothing useful, sir."
    return ' '.join(r.get('content', '') for r in results[:3])[:800]


if __name__ == '__main__':
    result = get_weather('Hyderabad')
    assert 'degrees' in result and any(char.isdigit() for char in result)
    # web_search without a key must fail gracefully, not crash
    if not os.getenv('TAVILY_API_KEY'):
        assert 'search' in web_search('anything').lower()
    print('tools self-check passed')
