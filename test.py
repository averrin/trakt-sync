from services.trakt_api import TraktAPI
import os
from dotenv import load_dotenv
import json

load_dotenv()
client_id = os.getenv('TRAKT_CLIENT_ID')
client_secret = os.getenv('TRAKT_CLIENT_SECRET')

trakt = TraktAPI(client_id, client_secret)

# 1. Check Dan Da Dan ID
dandadan_id = 'tt30217403'
print(f"\n--- Checking {dandadan_id} (Dan Da Dan) ---")
h = trakt.get_history(dandadan_id, type='shows')
for entry in h:
    ep = entry.get('episode', {})
    print(f"Entry: S{ep.get('season')}E{ep.get('number')} Date: {entry['watched_at']} (ID: {entry['id']})")

# 2. Check Missing IDs
missing_ids = ['tt26748649', 'tt8232636']
print(f"\n--- Checking Missing IDs {missing_ids} ---")
for mid in missing_ids:
    print(f"Checking {mid}...")
    # Fetch Show History
    h = trakt.get_history(mid, type='shows')
    # Filter by ID
    found = [x for x in h if x.get('show', {}).get('ids', {}).get('imdb') == mid]
    
    if not found:
        print(f"   No Show History for {mid}. (Total returned: {len(h)})")
        # Fetch Movie History
        h = trakt.get_history(mid, type='movies')
        found = [x for x in h if x.get('movie', {}).get('ids', {}).get('imdb') == mid]
    
    print(f"   Found Count: {len(found)}")
    
    if not found:
        print("   !!! TRULY MISSING !!!")
        
        # Try Adding it manually to see if it works
        print(f"   Attempting manual add for {mid} (S1E1)...")
        # Use datetime object for cleaner handling or correct string
        items = [{"ids": {"imdb": mid}, "type": "show", "season": 1, "episode": 1, "watched_at": "2024-01-01T12:00:00.000Z"}]
        # Note: add_to_history_batch logic in my class expects dicts with 'imdb_id', 'type', 'date' etc.
        # But I want to test raw payload.
        
        # Let's use the Class method if possible to test logic? 
        # No, test RAW API first.
        payload = {"shows": [{"ids": {"imdb": mid}, "seasons": [{"number": 1, "episodes": [{"number": 1, "watched_at": "2024-01-01T12:00:00.000Z"}]}]}]}
        
        import requests
        url = "https://api.trakt.tv/sync/history"
        try:
             resp = requests.post(url, json=payload, headers=trakt.headers)
             print(f"   Add Result: {resp.status_code}")
             print(json.dumps(resp.json(), indent=2))
        except Exception as e: print(e)