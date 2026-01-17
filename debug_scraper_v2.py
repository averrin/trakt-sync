import requests
import re
import base64
import urllib.parse

url = "https://hdrezka-home.tv/animation/adventures/20082-dyurarara-tv-1-2010.html"
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

print(f"Fetching {url}...")
try:
    response = requests.get(url, headers=headers, timeout=10)
    html = response.text
    
    # Regex from services/hdrezka.py
    help_links = re.findall(r'/help/([^/"\'\s]+)', html)
    
    print(f"Found {len(help_links)} potential help links.")
    
    for b64_part in help_links:
        print(f"Raw: {b64_part}")
        
        # 1. Strip slash
        b64_part = b64_part.rstrip('/')
        print(f"Stripped: {b64_part}")
        
        # 2. Pad
        b64_part += '=' * (-len(b64_part) % 4)
        print(f"Padded: {b64_part}")
        
        try:
            # 3. Decode Base64
            decoded_bytes = base64.b64decode(b64_part)
            decoded_str = decoded_bytes.decode('utf-8')
            print(f"Decoded B64: {decoded_str}")
            
            # 4. URL Unquote
            decoded_url = urllib.parse.unquote(decoded_str)
            print(f"Unquoted: {decoded_url}")
            
            if 'imdb.com/title/tt' in decoded_url:
                match = re.search(r'(tt\d+)', decoded_url)
                if match:
                    print(f"SUCCESS! Found IMDB ID: {match.group(1)}")
                else:
                    print("Match failed on decoded URL.")
            else:
                print("IMDB pattern not found in decoded URL.")
                
        except Exception as e:
            print(f"Processing Error: {e}")

except Exception as e:
    print(f"Request failed: {e}")
