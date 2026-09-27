import requests
import re

url = "https://open.spotifycdn.com/cdn/build/web-player/web-player.da8b87c8.js"
text = requests.get(url).text
for m in re.finditer(r'clienttoken', text, re.IGNORECASE):
    i = m.start()
    print("Match clienttoken:", text[max(0, i-100):min(len(text), i+200)])
