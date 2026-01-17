from playwright.sync_api import sync_playwright
import base64
import re
import requests
from utils.cache import Cache

class HDRezkaScraper:
    def __init__(self, username, password, headless=False):
        self.username = username
        self.password = password
        # self.headless = headless # User requested ALWAYS headless
        self.headless = True
        self.cache = Cache()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

    def get_watch_list(self):
        """
        Logs in and scrapes the list of items from the 'Continue Watching' page.
        Returns a list of dicts: {'url': str, 'title': str}
        """
        items = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context()
            page = context.new_page()
            
            print("Opening HDRezka...")
            try:
                page.goto("https://hdrezka-home.tv/", timeout=30000)
            except Exception as e:
                print(f"Error opening page: {e}")
                browser.close()
                return []
            
            # Login
            print("Logging in...")
            try:
                # Click login button to open modal
                page.click('.b-tophead__login', timeout=5000)
                page.fill('#login_name', self.username)
                page.fill('#login_password', self.password)
                page.press('#login_password', 'Enter')
                
                # Wait for login to complete (reduced timeout as requested)
                page.wait_for_selector('.b-tophead-logout', timeout=5000)
                print("Logged in successfully.")
            except Exception as e:
                print(f"Login failed or already logged in: {e}")
            
            print("Navigating to 'Continue Watching'...")
            page.goto("https://hdrezka-home.tv/continue/")
            page.wait_for_load_state('networkidle')
            
            item_rows = page.locator('div.b-videosaves__list_item').all()
            print(f"Found {len(item_rows)} items in list.")
            
            for row in item_rows:
                title_link = row.locator('.td.title a').first
                if title_link.count() == 0:
                    continue
                    
                url = title_link.get_attribute('href')
                if not url:
                    continue
                
                title = title_link.inner_text()
                full_url = url if url.startswith('http') else f"https://hdrezka-home.tv{url}"
                
                # Extract Date
                date_node = row.locator('.td.date')
                date_text = ""
                if date_node.count() > 0:
                    date_text = date_node.inner_text().strip()
                
                watched_date = None
                
                try:
                    from datetime import datetime, timedelta
                    import re
                    now = datetime.now()
                    
                    found_date_str = date_text
                    
                    # Fallback: Search in row text if specific node empty
                    if not found_date_str:
                        row_text = row.inner_text()
                        # Matches DD.MM.YYYY or DD-MM-YYYY
                        date_match = re.search(r'(\d{2}[.-]\d{2}[.-]\d{4})', row_text)
                        if date_match:
                            found_date_str = date_match.group(1)
                            print(f"[DEBUG] Found date via regex: {found_date_str}")

                    if 'сегодня' in found_date_str.lower():
                        watched_date = now
                    elif 'вчера' in found_date_str.lower():
                        watched_date = now - timedelta(days=1)
                    else:
                        # Try parsing various formats
                        # 19.12.2025 or 19-12-2025
                        clean_date = found_date_str.replace('.', '-')
                        # Regex to ensure we have DD-MM-YYYY
                        match = re.search(r'(\d{2}-\d{2}-\d{4})', clean_date)
                        if match:
                            watched_date = datetime.strptime(match.group(1), "%d-%m-%Y")
                            
                    print(f"[DEBUG] '{title}' -> Raw: '{date_text}' | Parsed: {watched_date}")
                            
                except Exception as e:
                    print(f"[DEBUG] Date parse error for '{title}': {e}")
                    pass # Keep None if parse fails

                # Extract Progress (Season/Episode)
                # Text is in .td.info, but we need to ignore .info-holder (which is "watch more")
                # We can grab inner_text and parse, or just grab the first text node.
                # inner_text returns "1 сезон 10 серия (Diva Universal) \n смотреть ещё..."
                
                info_text = row.locator('.td.info').inner_text()
                # Clean up newlines
                info_text = info_text.split('\n')[0].strip()
                
                # Regex for "X сезон Y серия"
                progress = None
                # Check for "X сезон Y серия"
                has_season = re.search(r'(\d+)\s+сезон\s+(\d+)\s+серия', info_text)
                if has_season:
                    progress = {
                        'season': int(has_season.group(1)),
                        'episode': int(has_season.group(2))
                    }
                
                items.append({
                    'url': full_url, 
                    'title': title, 
                    'progress': progress,
                    'date': watched_date
                })

            browser.close()
        return items

    def get_imdb_id(self, url):
        """
        Fetches the IMDB ID for a given URL.
        Checks cache first. If not cached, scrapes using requests.
        """
        # Check cache
        cached_id = self.cache.get_imdb_id(url)
        if cached_id:
            return cached_id, True

        # Scrape
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                html = response.text
                
                # Look for base64 obfuscated link
                # Pattern: href=".../help/BASE64..."
                # Regex to find the base64 string
                # We use [^/"']+ to match until a separator
                help_links = re.findall(r'/help/([^/"\'\s]+)', html)
                
                import urllib.parse
                
                for b64_part in help_links:
                    try:
                        # Fix padding if needed, though usually fine if matched correctly
                        # Strip trailing slash if caught
                        b64_part = b64_part.rstrip('/')
                        
                        # Pad
                        b64_part += '=' * (-len(b64_part) % 4)
                        
                        decoded_bytes = base64.b64decode(b64_part)
                        decoded_str = decoded_bytes.decode('utf-8')
                        
                        # It might be URL encoded
                        decoded_url = urllib.parse.unquote(decoded_str)
                        
                        if 'imdb.com/title/tt' in decoded_url:
                            match = re.search(r'(tt\d+)', decoded_url)
                            if match:
                                imdb_id = match.group(1)
                                self.cache.set_imdb_id(url, imdb_id)
                                return imdb_id, False
                    except Exception:
                        continue
                
                # Fallback: check for plain text or standard links
                # Some mirrors or old pages might have direct links
                # Also check specific span structures if known
                # <span class="imdb">IMDb: <span>7.8</span></span> - NO, that's rating
                
                match = re.search(r'imdb\.com/title/(tt\d+)', html)
                if match:
                     imdb_id = match.group(1)
                     self.cache.set_imdb_id(url, imdb_id)
                     return imdb_id, False
                     
                # Look for "IMDb" text and see if there is an ID nearby in a data attribute?
                # Sometimes it's in a hidden field or script.
                pass

        except Exception as e:
            # print(f"Error fetching {url}: {e}")
            pass
            
        return None, False

