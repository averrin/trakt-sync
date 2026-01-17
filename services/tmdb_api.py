import requests
import json
import time

TMDB_API_URL = "https://api.themoviedb.org"

class TMDBAPI:
    def __init__(self, api_key, access_token):
        self.api_key = api_key
        self.access_token = access_token
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json;charset=utf-8"
        }
        self.account_id = None # Will be fetched if needed, but not strictly required for v4 lists usually?
        # Actually v4 lists are owned by the token user.

    def find_by_imdb_id(self, imdb_id):
        """Finds a movie or TV show by IMDB ID."""
        url = f"{TMDB_API_URL}/3/find/{imdb_id}"
        params = {
            "external_source": "imdb_id",
            "language": "en-US" # Optional
        }
        
        try:
            response = requests.get(url, headers=self.headers, params=params)
            if response.status_code == 200:
                data = response.json()
                # Check movies result
                if data.get('movie_results'):
                    return {'type': 'movie', 'id': data['movie_results'][0]['id'], 'title': data['movie_results'][0]['title']}
                # Check tv results
                if data.get('tv_results'):
                    return {'type': 'tv', 'id': data['tv_results'][0]['id'], 'title': data['tv_results'][0]['name']}
            elif response.status_code == 429:
                # Rate limit
                retry = int(response.headers.get('Retry-After', 1)) 
                time.sleep(retry + 1)
                return self.find_by_imdb_id(imdb_id)
                
        except Exception as e:
            print(f"TMDB Find Error ({imdb_id}): {e}")
            
        return None

    def get_or_create_list(self, list_name="HDRezka Watched"):
        """Finds an existing v4 list by name or creates a new one."""
        # 1. Get User's Lists (v4)
        # GET /4/account/{account_object_id}/lists
        # But we need account_object_id. 
        # Alternatively, we can use GET /4/list/{list_id} if we knew it to check.
        # Let's try to get account info first.
        
        # Actually, simply listing user lists is easier with v4?
        # GET /4/account/{account_id}/lists
        # We need the account_id (IMDB v4 account id).
        # We can probably get it from the token? Or just creating duplicates??
        # Let's try to create and see if it fails/returns existing? usually creates duplicates.
        
        # Better: Search for list? No search api for lists.
        # Strategy: Save the list ID to a local file 'tmdb_list_id.json'.
        
        list_file = 'tmdb_list_id.json'
        try:
            if requests.os.path.exists(list_file):
                with open(list_file, 'r') as f:
                    return json.load(f)['list_id']
        except:
            pass
            
        # Create new list
        url = f"{TMDB_API_URL}/4/list"
        payload = {
            "name": list_name,
            "iso_639_1": "en",
            "public": False,
            "description": "Imported from HDRezka"
        }
        
        response = requests.post(url, headers=self.headers, json=payload)
        if response.status_code in [200, 201]:
            list_id = response.json()['id']
            print(f"Created TMDB List: {list_name} (ID: {list_id})")
            
            # Save it
            import os
            with open(list_file, 'w') as f:
                json.dump({'list_id': list_id}, f)
                
            return list_id
        else:
            print(f"Error creating list: {response.text}")
            return None

    def add_items_to_list(self, list_id, items):
        """
        Adds multiple items to a v4 list.
        items: list of {'media_type': 'movie'/'tv', 'media_id': 123}
        """
        if not items:
            return 0
            
        url = f"{TMDB_API_URL}/4/list/{list_id}/items"
        
        # TMDB v4 list add items endpoint might not support batching like this?
        # Documentation says: POST /4/list/{list_id}/items
        # Body: { "items": [ ... ] }
        # Yes, it supports batch.
        
        payload = {"items": items}
        
        try:
            response = requests.post(url, headers=self.headers, json=payload)
            if response.status_code == 429:
                wait = int(response.headers.get('Retry-After', 5))
                time.sleep(wait)
                return self.add_items_to_list(list_id, items)
                
            if response.status_code in [200, 201]:
                # returns results
                return len(items) 
            else:
                print(f"Error adding to list: {response.text}")
                return 0
        except Exception as e:
            print(f"TMDB Add List Error: {e}")
            return 0
