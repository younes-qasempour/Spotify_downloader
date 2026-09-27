import requests

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1"
})

r1 = session.get("https://open.spotify.com/", timeout=15)
print("Homepage status:", r1.status_code)
print("Session cookies:", session.cookies.get_dict())

session.headers.update({
    "Accept": "application/json",
    "Referer": "https://open.spotify.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Spotify-App-Version": "1.3.4.54.gce30f964531a"
})

r2 = session.get("https://open.spotify.com/get_access_token?reason=transport&productType=web_player", timeout=15)
print("Token status:", r2.status_code)
try:
    print("Token response:", r2.json())
except Exception as e:
    print("Error parsing json:", e, r2.text[:200])
