import requests
import webbrowser
import os
import json
import threading
import time
from utils.auth_server import get_auth_code

TRAKT_API_URL = 'https://api.trakt.tv'
REDIRECT_URI = 'http://localhost:8080/callback'
TOKEN_FILE = 'trakt_token.json'

class TraktAPI:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.headers = {
            'Content-Type': 'application/json',
            'trakt-api-version': '2',
            'trakt-api-key': self.client_id
        }
        self.lock = threading.Lock()
        self.load_token()

    def load_token(self):
        if os.path.exists(TOKEN_FILE):
            try:
                with open(TOKEN_FILE, 'r') as f:
                    data = json.load(f)
                    self.access_token = data.get('access_token')
                    if self.access_token:
                        self.headers['Authorization'] = f'Bearer {self.access_token}'
            except Exception as e:
                print(f"Error loading token: {e}")

    def save_token(self, data):
        try:
            with open(TOKEN_FILE, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Error saving token: {e}")

    def authenticate(self):
        with self.lock:
            # Double check inside lock
            if self.access_token: 
                 # Maybe check validity here if we did validation
                 return

            print("Authenticating with Trakt...")
            url = f"https://trakt.tv/oauth/authorize?response_type=code&client_id={self.client_id}&redirect_uri={REDIRECT_URI}"
            
            print(f"Opening browser: {url}")
            webbrowser.open(url)
            
            code = get_auth_code()
            if not code:
                raise Exception("Failed to get authorization code.")
                
            print(f"Got code. Exchanging for token...")
            response = requests.post(f'{TRAKT_API_URL}/oauth/token', json={
                'code': code,
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'redirect_uri': REDIRECT_URI,
                'grant_type': 'authorization_code'
            })
            
            if response.status_code == 200:
                data = response.json()
                self.access_token = data['access_token']
                self.headers['Authorization'] = f'Bearer {self.access_token}'
                self.save_token(data)
                print("Successfully authenticated with Trakt!")
            else:
                raise Exception(f"Authentication failed: {response.text}")

                raise Exception(f"Authentication failed: {response.text}")

    def _get_with_retry(self, url, description="data", retries=5):
        """Helper to perform GET request with retries for 423/429/5xx status."""
        if not self.access_token:
            self.authenticate()
            
        try:
            print(f"Fetching {description} from Trakt...")
            response = requests.get(url, headers=self.headers)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 423:
                 # 423 Locked Resource - usually means item/user is being indexed.
                 # Re-auth does NOT fix this. We should just wait.
                 if retries > 0:
                     wait = 5 # Standard wait
                     print(f"   [Trakt] Locked Resource (423). Waiting {wait}s to retry ({retries} left)...")
                     time.sleep(wait)
                     return self._get_with_retry(url, description, retries - 1)
                 else:
                     raise Exception(f"Trakt API Failed (423) after retries.")
                     
            elif response.status_code in [429, 500, 502, 503, 504]:
                if retries > 0:
                     msg = f"Status {response.status_code}"
                     wait = 2
                     if response.status_code == 429:
                         wait = int(response.headers.get('Retry-After', 2)) + 1
                     else:
                         wait = 5
                         
                     print(f"   [Trakt] {msg}. Waiting {wait}s to retry ({retries} left)...")
                     time.sleep(wait)
                     return self._get_with_retry(url, description, retries - 1)
                else:
                    raise Exception(f"Trakt API Failed ({response.status_code}) after retries.")
            elif response.status_code == 401:
                print("Token expired or invalid. Re-authenticating...")
                self.access_token = None
                self.authenticate()
                return self._get_with_retry(url, description, retries)
            else:
                # Other 4xx likely permanent
                raise Exception(f"Trakt API Error: {response.status_code} {response.text}")
                
        except Exception as e:
            raise e

    def get_watched_shows(self, load_progress=False):
        """Fetches list of all watched shows from Trakt."""
        # Query Params
        params = 'extended=noseasons'
        if load_progress:
            params = '' 
        
        try:
            data = self._get_with_retry(f'{TRAKT_API_URL}/sync/watched/shows?{params}', "watched shows")
            
            watched = {}
            for item in data:
                ids = item.get('show', {}).get('ids', {})
                imdb = ids.get('imdb')
                if imdb:
                    watched[imdb] = item
            return watched
        except Exception as e:
            print(f"CRITICAL ERROR: Could not fetch watched shows: {e}")
            # Reraise so main.py aborts!
            raise e

    def get_watched_movies(self):
        """Fetches list of all watched movies from Trakt."""
        try:
            data = self._get_with_retry(f'{TRAKT_API_URL}/sync/watched/movies', "watched movies")
            
            watched = {}
            for item in data:
                ids = item.get('movie', {}).get('ids', {})
                imdb = ids.get('imdb')
                if imdb:
                    watched[imdb] = item
            return watched
        except Exception as e:
             print(f"CRITICAL ERROR: Could not fetch watched movies: {e}")
             raise e

    def search_by_imdb(self, imdb_id, retries=5):
        if not self.access_token:
             self.authenticate()

        try:
            response = requests.get(f'{TRAKT_API_URL}/search/imdb/{imdb_id}?type=movie,show', headers=self.headers)
            
            if response.status_code == 200:
                results = response.json()
                if results:
                    return results[0]
            elif response.status_code == 401:
                print("Token expired or invalid. Re-authenticating...")
                self.access_token = None
                self.authenticate()
                return self.search_by_imdb(imdb_id, retries)
            elif response.status_code == 429:
                if retries > 0:
                    wait = int(response.headers.get('Retry-After', 2)) + 1
                    time.sleep(wait)
                    return self.search_by_imdb(imdb_id, retries - 1)
                else:
                    return None
            
        except Exception:
            pass
            
        return None

    def get_history(self, id_val, type='shows', limit=1000):
        """
        Fetch history for a specific item (show/movie).
        type: 'shows' or 'movies'
        id_val: Trakt ID, Slug, or IMDB ID
        """
        # Use generic get with retry
        url = f'{TRAKT_API_URL}/sync/history/{type}/{id_val}?limit={limit}'
        try:
            return self._get_with_retry(url, f"history for {type}/{id_val}")
        except Exception as e:
            print(f"Error fetching history: {e}")
            # Use empty list only if 100% sure, but here exception is safer to bubble up?
            # Existing callers expect list. If we raise, main.py might crash.
            # But crashing is better than "Missing".
            # If I return [], it looks like "No history".
            # I should re-raise or return None?
            # Code expects list.
            # Let's re-raise and modify main.py? 
            # No, keep it simple. main.py wrapped in try/except block now.
            raise e

    def add_to_history(self, item, retries=5):
        # ... (keep existing single item method if needed, or just rely on batch)
        # For compatibility with old code or single adds
        if not self.access_token:
             self.authenticate()

        payload = {}
        if item['type'] == 'movie':
            payload['movies'] = [{'ids': item['movie']['ids']}]
        elif item['type'] == 'show':
            payload['shows'] = [{'ids': item['show']['ids']}]
            
        return self._post_history(payload, retries)

    def add_to_history_batch(self, imdb_ids, retries=5):
        """Adds a batch of items by IMDB ID to history."""
        if not self.access_token:
             self.authenticate()
             
        # Trakt allows mixing movies and shows in the payload, 
        # but we need to know which is which?
        # Actually, Trakt's sync/history endpoint specifically accepts objects with IDs.
        # If we only have IMDB IDs, we might not strictly know if it's a movie or show 
        # without searching first.
        # However, we can try adding them to *both* or check if Trakt accepts generic IDs?
        # Trakt payload structure:
        # {
        #   "movies": [ {"ids": {"imdb": "tt..."}} ],
        #   "shows":  [ {"ids": {"imdb": "tt..."}} ]
        # }
        # The issue is we don't know if a "tt..." is a movie or show just from the ID 
        # (usually movies, but shows have tt ids too).
        # But wait, in the previous code we were SEARCHING first.
        # To avoid searching 1-by-1, we can try to rely on Trakt's smarts, 
        # OR we just put them in 'movies' and 'shows'?? No that duplicates.
        
        # Strategy:
        # 1. We still might need to distinguish commands. 
        #    BUT, searching 400 items is also 400 calls.
        #    Does Trakt have a batch search? No.
        #    Does Trakt history accept just IDs?
        #    Testing: Usually people do a lookup. 
        #    Optimization: 
        #    - HDRezka URL usually tells us! /films/ or /series/ or /cartoons/
        #    - We can use that hint!
        
        movies = []
        shows = []
        
        for item in imdb_ids:
            # item is expected to be dict {'imdb_id': 'tt...', 'type': 'movie'/'show', 'progress': {...}, 'date': datetime}
            ids = {}
            if item.get('trakt_id'):
                ids['trakt'] = item['trakt_id']
            else:
                ids['imdb'] = item['imdb_id']
            
            obj = {"ids": ids}
            
            # Prepare watched_at string
            watched_at_str = None
            if item.get('date'):
                # Set to Noon UTC to be safe/neutral
                watched_at_str = item['date'].strftime('%Y-%m-%dT12:00:00.000Z')
                obj['watched_at'] = watched_at_str

            if item['type'] == 'movie':
                movies.append(obj)
            else:
                # SHOW
                progress = item.get('progress')
                if progress:
                    # Sync "Watched Up To"
                    # 1. Mark all previous seasons as fully watched
                    seasons_list = []
                    current_season = progress['season']
                    current_episode = progress['episode']
                    
                    # Add previous seasons (assuming standard S1 start)
                    # Add previous seasons (assuming standard S1 start)
                    for s in range(1, current_season):
                        season_obj = {"number": s}
                        if watched_at_str:
                             season_obj["watched_at"] = watched_at_str
                        seasons_list.append(season_obj)
                        
                    # 2. Mark current season up to current episode
                    # Create list of episodes 1..current_episode
                    # Apply watched_at to EPISODES specifically (Trakt quirk?)
                    episodes_list = []
                    for e in range(1, current_episode + 1):
                        ep_obj = {"number": e}
                        if watched_at_str:
                             ep_obj["watched_at"] = watched_at_str
                        episodes_list.append(ep_obj)
                    
                    seasons_list.append({
                        "number": current_season,
                        "episodes": episodes_list
                    })
                    
                    obj["seasons"] = seasons_list
                    shows.append(obj)
                else:
                    # Sync whole show
                    shows.append(obj)
                
        payload = {}
        if movies: payload['movies'] = movies
        if shows: payload['shows'] = shows
        
        if not payload:
            return None
            
        # DEBUG: Print payload (truncated if too long mostly)
        # print(f"[DEBUG] Trakt Payload: {json.dumps(payload)}") 
        # Actually proper debug might spam, but helpful for single item check.
        
        return self._post_history(payload, retries)

    def _post_history(self, payload, retries=5):
        try:
            response = requests.post(f'{TRAKT_API_URL}/sync/history', json=payload, headers=self.headers)
            
            if response.status_code == 201:
                res = response.json()
                # Log the result summary (added vs not found)
                # print(f"[DEBUG] Trakt Sync Response: Added={res.get('added')} NotFound={res.get('not_found')}")
                return res
            elif response.status_code == 401:
                print("Token expired or invalid. Re-authenticating...")
                self.access_token = None
                self.authenticate()
                return self._post_history(payload, retries)
            elif response.status_code == 429:
                if retries > 0:
                    wait = int(response.headers.get('Retry-After', 2)) + 1
                    print(f"  Rate Limit (429). Waiting {wait}s...")
                    time.sleep(wait)
                    return self._post_history(payload, retries - 1)
                else:
                    return None
            else:
                 try:
                    return response.json()
                 except: 
                    return None
                    
        except Exception:
            pass
        return None

    def remove_history_ids(self, history_ids):
        """Remove specific history entries by their History ID."""
        if not history_ids:
            return
            
        payload = {"ids": history_ids}
        return self._post_remove(payload)

    def remove_from_history_batch(self, imdb_ids, retries=5):
        """Removes a batch of items by IMDB ID from history."""
        if not self.access_token:
             self.authenticate()
             
        movies = []
        shows = []
        
        for item in imdb_ids:
            # { "shows": [ { "ids": { "imdb": "tt..." } } ] } -> removes all history for that show.
            
            ids = {}
            if item.get('trakt_id'):
                ids['trakt'] = item['trakt_id']
            else:
                ids['imdb'] = item['imdb_id']
            
            obj = {"ids": ids}
            if item['type'] == 'movie':
                movies.append(obj)
            else:
                # Granular removal if progress exists (safe for Backfilling)
                # But if 'wipe' is True, we want to remove the WHOLE show.
                wipe = item.get('wipe', False)
                
                if item.get('progress') and not wipe:
                    prog = item['progress']
                    obj["seasons"] = [{
                        "number": prog['season'],
                        "episodes": [{"number": prog['episode']}]
                    }]
                shows.append(obj) 
                
        payload = {}
        if movies: payload['movies'] = movies
        if shows: payload['shows'] = shows
        
        if not payload:
            return None
            
        return self._post_remove(payload, retries)

    def _post_remove(self, payload, retries=5):
        try:
            response = requests.post(f'{TRAKT_API_URL}/sync/history/remove', json=payload, headers=self.headers)
            
            if response.status_code == 200:
                data = response.json()
                deleted = data.get('deleted', {})
                not_found = data.get('not_found', {})
                # print(f"  [Trakt Remove] Deleted: {deleted} | Not Found: {not_found}")
                return data
            elif response.status_code == 401:
                print("Token expired or invalid. Re-authenticating...")
                self.access_token = None
                self.authenticate()
                return self._post_remove(payload, retries)
            elif response.status_code == 429:
                if retries > 0:
                    wait = int(response.headers.get('Retry-After', 2)) + 1
                    print(f"  Rate Limit (429). Waiting {wait}s...")
                    time.sleep(wait)
                    return self._post_remove(payload, retries - 1)
                else:
                    return None
            else:
                 try:
                    return response.json()
                 except: 
                    return None
                    
        except Exception as e:
            print(f"Error in remove: {e}")
        return None
