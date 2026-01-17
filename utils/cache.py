import json
import os
import threading

CACHE_FILE = 'cache.json'

class Cache:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, cache_file=CACHE_FILE):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(Cache, cls).__new__(cls)
                cls._instance.cache_file = cache_file
                cls._instance.data = cls._instance._load_cache()
                cls._instance.lock = threading.Lock()
        return cls._instance

    def __init__(self, cache_file=CACHE_FILE):
        # Init logic moved to __new__ to prevent re-loading on every instantiation
        pass

    def _load_cache(self):
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {}
        return {}

    def save_cache(self):
        with self.lock:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=4)

    def get_imdb_id(self, url):
        with self.lock:
            val = self.data.get(url)
            if isinstance(val, dict):
                return val.get('id')
            return val

    def get_status(self, url):
        with self.lock:
            val = self.data.get(url)
            if isinstance(val, dict):
                return val.get('status')
            return None

    def set_imdb_id(self, url, imdb_id):
        with self.lock:
            # Preserve existing status if it was a dict
            current = self.data.get(url)
            if isinstance(current, dict):
                current['id'] = imdb_id
                self.data[url] = current
            else:
                self.data[url] = {
                    'id': imdb_id,
                    'status': 'active' # Default status
                }
        self.save_cache()

    def get_trakt_data(self, url):
        with self.lock:
            val = self.data.get(url)
            if isinstance(val, dict):
                return val.get('trakt_data')
            return None

    def set_trakt_data(self, url, trakt_data):
        with self.lock:
            current = self.data.get(url)
            if isinstance(current, dict):
                current['trakt_data'] = trakt_data
                self.data[url] = current
            else:
                # If it was a string ID or None, upgrade it
                imdb_id = current if isinstance(current, str) else None
                self.data[url] = {
                    'id': imdb_id,
                    'trakt_data': trakt_data,
                    'status': 'active'
                }
        self.save_cache()

    def set_status(self, url, status):
        with self.lock:
            current = self.data.get(url)
            if isinstance(current, dict):
                current['status'] = status
                self.data[url] = current
            else:
                # Upgrade to dict (keeping ID if it was string)
                imdb_id = current if isinstance(current, str) else None
                self.data[url] = {
                    'id': imdb_id,
                    'status': status
                }
        self.save_cache()

    def get_date(self, url):
        with self.lock:
            val = self.data.get(url)
            if isinstance(val, dict):
                return val.get('date')
            return None

    def set_date(self, url, date_str):
        """Stores the watch date string (e.g., DD-MM-YYYY) in cache."""
        with self.lock:
            current = self.data.get(url)
            if isinstance(current, dict):
                current['date'] = date_str
                self.data[url] = current
            else:
                # Should normally be a dict by the time we have a date, but handle upgrade
                imdb_id = current if isinstance(current, str) else None
                self.data[url] = {
                    'id': imdb_id,
                    'date': date_str,
                    'status': 'active'
                }
        self.save_cache()

    def get_all_items(self):
        with self.lock:
            # Return copy to avoid thread issues
            return dict(self.data)

