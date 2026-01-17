import requests
import re
import base64

url = "https://hdrezka-home.tv/animation/adventures/20082-dyurarara-tv-1-2010.html"
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

print(f"Fetching {url}...")
try:
    response = requests.get(url, headers=headers, timeout=10)
    print(f"Status Code: {response.status_code}")
    
    html = response.text
    print(f"HTML Length: {len(html)}")
    
    # Check for help links
    help_links = re.findall(r'/help/([A-Za-z0-9+/=]+)', html)
    print(f"Found {len(help_links)} help links.")
    
    for b64_part in help_links:
        try:
            decoded_url = base64.b64decode(b64_part).decode('utf-8')
            print(f"Decoded: {decoded_url}")
            if 'imdb.com/title/tt' in decoded_url:
                print("  -> MATCH FOUND!")
        except Exception as e:
            print(f"  Decode error: {e}")

    # Check for direct links
    match = re.search(r'imdb\.com/title/(tt\d+)', html)
    if match:
        print(f"Direct Match Found: {match.group(1)}")
    else:
        print("No direct match found.")
        
    # Check if blocked
    if "Cloudflare" in html:
        print("Page contains 'Cloudflare' - likely blocked.")
        
except Exception as e:
    print(f"Request failed: {e}")
