import os
import argparse
from dotenv import load_dotenv
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from datetime import datetime
from services.trakt_api import TraktAPI
from services.hdrezka import HDRezkaScraper

load_dotenv()

TRAKT_CLIENT_ID = os.getenv('TRAKT_CLIENT_ID')
TRAKT_CLIENT_SECRET = os.getenv('TRAKT_CLIENT_SECRET')

HDREZKA_USERNAME = os.getenv('HDREZKA_USERNAME')
HDREZKA_PASSWORD = os.getenv('HDREZKA_PASSWORD')

def process_id_resolution(item, scraper, trakt):
    """
    Phase 1: Just get the IMDB ID and Metadata.
    Returns: (imdb_id, type_hint, status, title, progress)
    """
    url = item['url']
    title = item['title']
    
    # Progress is already in item if we passed it from scraper
    progress = item.get('progress')

    # 1. Check Cache for Trakt Data (Authoritative)
    trakt_data = scraper.cache.get_trakt_data(url)
    
    imdb_id = None
    item_type = None
    status = "Scraped"
    
    if trakt_data:
        # We have full metadata!
        imdb_id = trakt_data.get('ids', {}).get('imdb')
        item_type = trakt_data.get('type') # 'movie' or 'show'
        status = "Cached (Trakt)"
    else:
        # 2. Get ID (from cache or scrape) - this is just ID, no metadata yet
        # scraper.get_imdb_id handles its own cache for ID only
        imdb_id, is_cached = scraper.get_imdb_id(url)
        status = "Cached (ID)" if is_cached else "Scraped (ID)"
        
        if imdb_id:
            # 3. Fetch Trakt Metadata for this ID
            # This is critical to know if it's movie or show
            # We use the search endpoint
            trakt_result = trakt.search_by_imdb(imdb_id)
            if trakt_result:
                 # result is like { 'type': 'movie', 'movie': {...}, 'score': ... }
                 item_type = trakt_result.get('type')
                 inner_data = trakt_result.get(item_type) # dict of movie/show details
                 
                 # Save to cache!
                 save_data = inner_data.copy()
                 save_data['type'] = item_type
                 
                 scraper.cache.set_trakt_data(url, save_data)
                 status += " -> Trakt Resolved"
                 if imdb_id == 'tt0118401':
                     print(f"[DEBUG-TRACE] Processed tt0118401 from {url}")
                 # print(f"[DEBUG] Trakt Lookup Success: {url} -> {item_type}")
            else:
                 status += " -> Trakt Lookup Failed"
                 # print(f"[DEBUG] Trakt Lookup Failed: {imdb_id}")

    # Fallback / Override logic
    # If Trakt said nothing, we use heuristics
    if not item_type:
        # Simple heuristic for type from URL
        item_type = 'movie'
        if '/series/' in url:
            item_type = 'show'
        elif '/cartoons/' in url or '/animation/' in url:
            if progress:
                item_type = 'show'
            # else assume movie
        
        # Override: If progress exists, it MUST be a show
        if progress:
            item_type = 'show'
    
    return imdb_id, item_type, status, title, progress

def get_trakt_progress(trakt_item):
    """
    Extracts the latest watched progress from a Trakt item.
    Returns: (season, episode) or (0, 0) if none found.
    """
    if not trakt_item or 'seasons' not in trakt_item:
        return 0, 0
        
    seasons = trakt_item['seasons']
    max_season = 0
    max_episode = 0
    
    for season in seasons:
        s_num = season.get('number', 0)
        # We generally track the highest season watched
        if s_num > max_season:
            max_season = s_num
            # Reset max episode for new max season, then find max in this season
            # Actually, we need the max episode OF the max season.
            episodes = season.get('episodes', [])
            current_max_ep = 0
            for ep in episodes:
                e_num = ep.get('number', 0)
                if e_num > current_max_ep:
                    current_max_ep = e_num
            max_episode = current_max_ep
            
        elif s_num == max_season:
            # Same max season, check if higher episode (unlikely in sorted list but good to be safe)
            episodes = season.get('episodes', [])
            for ep in episodes:
                e_num = ep.get('number', 0)
                if e_num > max_episode:
                    max_episode = e_num
                    
    return max_season, max_episode

def deduplicate_item(trakt, imdb_id, itype='shows', dry_run=False):
    # Fetch history
    history = trakt.get_history(imdb_id, type=itype)
    if not history:
        return

    # Group by Unique Key (Season/Ep for shows, ID for movies)
    groups = {}
    for entry in history:
        hid = entry['id']
        watched_at = entry['watched_at']
        
        key = None
        if itype == 'shows':
            s = entry.get('episode', {}).get('season')
            e = entry.get('episode', {}).get('number')
            if s is not None and e is not None:
                key = (s, e)
        else:
             # For movies, just one entry allowed
             key = 'movie'
             
        if key:
            if key not in groups:
                groups[key] = []
            groups[key].append({'id': hid, 'date': watched_at})

    # Find duplicates
    ids_to_remove = []
    
    for key, entries in groups.items():
        if len(entries) > 1:
            # Sort by date (Oldest first)
            entries.sort(key=lambda x: x['date'])
            
            # Keep the OLDEST (index 0) and remove the rest
            duplicates = entries[1:]
            for d in duplicates:
                ids_to_remove.append(d['id'])
                
    if ids_to_remove:
        print(f"   [Dedupe] {imdb_id}: Removing {len(ids_to_remove)} duplicate entries.")
        trakt.remove_history_ids(ids_to_remove)

def deduplicate_item(trakt, imdb_id, itype='shows'):
    # Fetch history
    history = trakt.get_history(imdb_id, type=itype)
    if not history:
        return

    # Group by Unique Key (Season/Ep for shows, ID for movies)
    groups = {}
    for entry in history:
        hid = entry['id']
        watched_at = entry['watched_at']
        
        key = None
        if itype == 'shows':
            s = entry.get('episode', {}).get('season')
            e = entry.get('episode', {}).get('number')
            if s is not None and e is not None:
                key = (s, e)
        else:
             # For movies, just one entry allowed
             key = 'movie'
             
        if key:
            if key not in groups:
                groups[key] = []
            groups[key].append({'id': hid, 'date': watched_at})

    # Find duplicates
    ids_to_remove = []
    
    for key, entries in groups.items():
        if len(entries) > 1:
            # Sort by date (Oldest first)
            entries.sort(key=lambda x: x['date'])
            
            # Keep the OLDEST (index 0) and remove the rest
            duplicates = entries[1:]
            for d in duplicates:
                ids_to_remove.append(d['id'])
                
    if ids_to_remove:
        print(f"   [Dedupe] {imdb_id}: Removing {len(ids_to_remove)} duplicate entries.")
        if not dry_run:
            trakt.remove_history_ids(ids_to_remove)
        else:
            print(f"   [Dry Run] Would remove {len(ids_to_remove)} IDs.")

def flatten_show_history(trakt, imdb_id, target_date_str):
    """
    Fetches ALL watched episodes for a show, wipes history, 
    and re-adds them all with the specific target_date.
    Preserves 'Watched' status while fixing dates.
    """
    print(f"   [Flatten] Fetching full history for {imdb_id}...")
    history = trakt.get_history(imdb_id, type='shows', limit=10000)
    if not history:
        print("   [Flatten] No history found to flatten.")
        return

    # Extract unique episodes
    # Use Trakt ID for precision
    # Item structure: {'id': 123, 'episode': {'ids': {'trakt': ...}}}
    unique_eps = {}
    for h in history:
        ep_data = h.get('episode')
        if not ep_data: continue
        
        t_id = ep_data.get('ids', {}).get('trakt')
        if t_id and t_id not in unique_eps:
            unique_eps[t_id] = ep_data['ids']
            
    print(f"   [Flatten] Found {len(unique_eps)} unique episodes. Wiping and re-adding with date {target_date_str}...")
    
    # 1. Wipe
    # We use the generic wipe payload (by IMDB ID of show) to clear everything quickly
    # Must provide 'type' and 'wipe' to remove_from_history_batch
    trakt.remove_from_history_batch([
        {'imdb_id': imdb_id, 'type': 'show', 'wipe': True}
    ])
    
    # 2. Re-Add Batch
    # Construct items. 
    # API limit per request? Trakt is lenient, but maybe split if huge?
    # Let's try one batch.
    items = []
    # format date to ISO? 'watched_at' expects ISO 8601.
    # target_date_str is DD-MM-YYYY.
    # Convert to ISO.
    iso_date = None
    try:
        dt = datetime.strptime(target_date_str, "%d-%m-%Y")
        iso_date = dt.strftime("%Y-%m-%dT12:00:00.000Z")
    except:
        print(f"   [Flatten] Invalid date format {target_date_str}, using NOW.")
        iso_date = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        
    for ids in unique_eps.values():
        items.append({
            "ids": ids,
            "watched_at": iso_date
        })
        
    # Send
    # We don't have a batch add method exposed cleanly that takes raw items?
    # trakt.add_to_history takes "item" which is {movie:..., show:...}
    # We need to construct a "episodes": [...] payload.
    # Send
    payload = {"episodes": items}
    url = f"https://api.trakt.tv/sync/history"
    try:
        if not dry_run:
            trakt._post(url, payload)
            print(f"   [Flatten] Successfully re-added {len(items)} episodes.")
        else:
             print(f"   [Dry Run] Would flatten re-add {len(items)} episodes.")
    except Exception as e:
        print(f"   [Flatten] Error re-adding: {e}")

def sync_completed_from_cache(trakt, cache, dry_run=False):
    """
    Iterates through cache. If item is 'completed', ensure it is fully watched on Trakt with correct date.
    Deduplicates by IMDb ID (choosing latest date) to prevent conflicts.
    """
    print("\n=== Syncing 'Completed' Status from Cache ===")
    
    # 1. Get all completed items from cache and Group by ID
    completed_groups = {} # {imdb_id: [item1, item2]}
    
    for url, data in cache.items():
        if isinstance(data, dict) and data.get('status') == 'completed':
            if data.get('id'):
                mid = data.get('id')
                if mid not in completed_groups:
                    completed_groups[mid] = []
                completed_groups[mid].append(data)
                
    print(f"Found {len(completed_groups)} unique completed shows/movies in cache.")
    
    # 2. Check Trakt
    watched = trakt.get_watched_shows(load_progress=True)
    watched_movies = trakt.get_watched_movies()
    if watched_movies:
        watched.update(watched_movies)
    
    items_to_sync = [] # List of unique representative items
    items_to_remove = [] # Mismatches need wipe first
    
    for imdb_id, group in tqdm(completed_groups.items(), desc="Checking Completed"):
        # Select best candidate from group (latest date)
        best_item = group[0]
        max_date = None
        
        # Determine max date among duplicates
        for it in group:
            d_str = it.get('date')
            if d_str:
                try:
                    dt = datetime.strptime(d_str, "%d-%m-%Y")
                    if max_date is None or dt > max_date:
                        max_date = dt
                        best_item = it # Use this item as representative
                except: pass
        
        c_date_str = max_date.strftime("%d-%m-%Y") if max_date else None
        
        t_data = best_item.get('trakt_data', {})
        title = t_data.get('title', imdb_id)
        
        # Check Trakt State
        if imdb_id in watched:
            t_item = watched[imdb_id]
            t_last_w = t_item.get('last_watched_at')
            t_date_str = "None"
            if t_last_w:
                try:
                    dt = datetime.strptime(t_last_w[:10], "%Y-%m-%d")
                    t_date_str = dt.strftime("%d-%m-%Y")
                except: pass
            
            # Compare Dates
            if c_date_str and t_date_str != c_date_str:
                 print(f"   [Date Mismatch] {title}: Trakt {t_date_str} != Cache {c_date_str}. Fixing...")
                 
                 # Prepare representative for sync
                 sync_rep = best_item.copy()
                 sync_rep['date'] = c_date_str # Ensure string format matches what we determined
                 
                 items_to_sync.append(sync_rep)
                 items_to_remove.append(sync_rep) 
                 continue

            pass
        else:
             print(f"   [Missing] {title} ({imdb_id}) marked completed in cache but missing on Trakt.")
             sync_rep = best_item.copy()
             if c_date_str:
                 sync_rep['date'] = c_date_str
             items_to_sync.append(sync_rep)

    # Handle Removals
    if items_to_remove:
        print(f"   Wiping history for {len(items_to_remove)} items to fix dates...")
        
        rem_payload = []
        for it in items_to_remove:
             rem_payload.append({
                 "imdb_id": it['id'],
                 "type": it.get('trakt_data', {}).get('type', 'show'), 
                 "wipe": True
             })
             
        batch_size = 100
        chunks = [rem_payload[i:i + batch_size] for i in range(0, len(rem_payload), batch_size)]
        
        import sys
        import time
        for chunk in tqdm(chunks, desc="Cleaning History", file=sys.stdout):
             if not dry_run:
                 trakt.remove_from_history_batch(chunk)
                 time.sleep(2)
             else:
                 print(f"   [Dry Run] Would wipe mismatch items.")

    if items_to_sync:
        print(f"   Enforcing 'Completed' status for {len(items_to_sync)} items...")
        
        batch_list = []
        for it in items_to_sync:
            # Determine type from cache or default to show
            itype = 'show'
            if it.get('trakt_data', {}).get('type') == 'movie':
                itype = 'movie'
                
            # Use cached date (we already processed best date into 'date' key or it's native)
            date_val = None
            date_str = it.get('date') 
            if date_str:
                try:
                     # Check if it's already datetime? No, we set string above/read string
                    if isinstance(date_str, str):
                        date_val = datetime.strptime(date_str, "%d-%m-%Y")
                    else:
                        date_val = date_str # assume weird case
                except: pass

            obj = {
                "imdb_id": it['id'],
                "type": itype,
                "date": date_val 
            }
            batch_list.append(obj)
            
        if not dry_run:
            results = trakt.add_to_history_batch(batch_list)
            print(f"   [Completed Sync] Configured {len(batch_list)} shows as Watched.")
        else:
            print(f"   [Dry Run] Would batch sync {len(batch_list)} completed items.")

def start(resync=False, headless=False, fix_duplicates=False, fix_mismatch=False, dry_run=False):
    # If run from CLI, args might be passed via sys.argv, but we can't easily mix 
    # explicit args and argparse if we call start() directly.
    # Pattern: ArgumentParser parses sys.argv only if no args passed to function? 
    # Better: Move argparse logic to `if __name__ == "__main__":` block or handling inside start
    
    # We'll allow explicit parameters. If they are defaults, we check CLI usage only if main?
    # Simpler: start() accepts params. CLI calls start(args.resync).
    
    print("Starting TraktSync...")
    if resync:
        print(">>> FORCE RESYNC MODE ENABLED <<<")
        print("    Items will be REMOVED from Trakt history before syncing (unless Trakt is ahead).")
    
    if dry_run:
        print(">>> DRY RUN MODE <<<")
        print("    No changes will be sent to Trakt.")
    
    if not TRAKT_CLIENT_ID or not TRAKT_CLIENT_SECRET:
        print("Error: TRAKT_CLIENT_ID and TRAKT_CLIENT_SECRET must be set in .env")
        return

    # Initialize Services
    trakt = TraktAPI(TRAKT_CLIENT_ID, TRAKT_CLIENT_SECRET)
    try:
        trakt.authenticate()
    except Exception as e:
        print(f"Trakt Auth failed: {e}")
        return

    # Check Credentials
    username = HDREZKA_USERNAME
    password = HDREZKA_PASSWORD
    if not username or not password:
        print("HDRezka credentials not found in env.")

    scraper = HDRezkaScraper(username, password, headless=headless)
    
    if fix_duplicates:
        print("\n=== Running Deduplication Scan ===")
        # target specific ID if needed, or all from cache
        # For now, let's scan ALL cached items that have an ID.
        cached_items = scraper.cache.data
        print(f"Scanning {len(cached_items)} items from cache...")
        
        # We need to iterate over a COPY because we might not modify it but it's safer
        # Actually we iterate data directly
        for url, data in tqdm(cached_items.items(), desc="Deduplicating"):
             if isinstance(data, dict):
                 imdb_id = data.get('id')
                 if not imdb_id or not imdb_id.startswith('tt'):
                     continue
                 
                 # Only check shows? Or movies too?
                 # Midsomer Murders is a show. Duplicates usually happen in shows.
                 # Let's assume shows for now, or check type if available.
                 trakt_data = data.get('trakt_data')
                 itype = 'shows'
                 if trakt_data and trakt_data.get('type') == 'movie':
                     itype = 'movies'
                 
                 deduplicate_item(trakt, imdb_id, itype, dry_run=dry_run)
                 
        print("Deduplication complete.")
        return
    
    
    # [Completed Authority] from Cache (NEW)
    try:
        # 1. Sync completed items (Handles its own fetching, basic)
        sync_completed_from_cache(trakt, scraper.cache.data, dry_run=dry_run)
    
        # 2. Fetch Trakt Watched State (Optimized)
        # We now request FULL progress (load_progress=True) to compare
        trakt_watched = trakt.get_watched_shows(load_progress=True)
        trakt_movies = trakt.get_watched_movies()
        if trakt_movies:
            trakt_watched.update(trakt_movies)
    except Exception as e:
        print(f"\n[CRITICAL] Aborting Sync: {e}")
        return
    
    print("Fetching Watch List from HDRezka...")
    watch_list = scraper.get_watch_list()
    
    if not watch_list:
        print("No items found or login failed.")
        return
        
    # --- Phase 1: Resolve Repositories ---
    print(f"\nPhase 1: Resolving IMDB IDs for {len(watch_list)} items...")
    
    resolved_items = []
    failed_resolution = []
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_item = {executor.submit(process_id_resolution, item, scraper, trakt): item for item in watch_list}
        
        import sys
        with tqdm(total=len(watch_list), desc="Resolving IDs", file=sys.stdout) as pbar:
            for future in as_completed(future_to_item):
                item = future_to_item[future]
                imdb_id, item_type, status, title, progress = future.result()
                
                if imdb_id:
                    # --- Back-Sync / Cache Logic ---
                    cached_status = scraper.cache.get_status(item['url'])
                    
                    # Update Date in Cache (if we have it)
                    if item.get('date'):
                        d_str = item['date'].strftime("%d-%m-%Y")
                        # Only update if different? 
                        # Actually just update, set_date is safe
                        scraper.cache.set_date(item['url'], d_str)
                    
                    resolved_items.append({
                        'imdb_id': imdb_id,
                        'trakt_id': scraper.cache.get_trakt_data(item['url']).get('ids', {}).get('trakt') if scraper.cache.get_trakt_data(item['url']) else None,
                        'type': item_type,
                        'title': title,
                        'progress': progress,
                        'url': item['url'],
                        'date': item.get('date'),
                        'cached_status': cached_status
                    })
                    pbar.set_postfix_str(f"{status}: {title[:20]}")
                else:
                    failed_resolution.append(f"{title} (No IMDB ID)")
                    pbar.set_postfix_str(f"Failed: {title[:20]}")
                
                pbar.update(1)

    # Report Detected Progress & Back-Sync Candidates
    print("\n--- Detected Progress & Status ---")
    
    final_sync_list = []
    items_to_remove = []
    
    for item in resolved_items:
        imdb_id = item['imdb_id']
        title = item['title']
        progress = item.get('progress')
        rezka_date = item.get('date')
        cached_status = item['cached_status']
        
        # Build Info String
        info = f"{title}"
        if progress:
            info += f" -> HDRezka: S{progress['season']}E{progress['episode']}"
        else:
            info += f" -> HDRezka: Watched" 

        # 1. Check Cache Status
        if cached_status == 'ignored':
            print(f"{info} | [IGNORED] - Skipping Sync (User Flag)")
            continue

        # 2. Check Trakt Status
        should_sync = True
        force_wipe = False
        trakt_ahead = False
        

        
        if imdb_id in trakt_watched:
            trakt_item = trakt_watched[imdb_id]
            
            t_season = 0
            t_episode = 0
            if 'show' in trakt_item:
                 t_season, t_episode = get_trakt_progress(trakt_item)
            
            # Trakt Last Watched Date
            t_last_watched = trakt_item.get('last_watched_at')
            t_date_str = "None"
            if t_last_watched:
                # ISO Format: 2014-09-22T21:00:00.000Z
                try:
                    t_date_dt = datetime.strptime(t_last_watched[:10], "%Y-%m-%d")
                    t_date_str = t_date_dt.strftime("%d-%m-%Y")
                except:
                    t_date_dt = None
            else:
                t_date_dt = None

            # Rezka Date String for comparison
            r_date_str = rezka_date.strftime("%d-%m-%Y") if rezka_date else "None"
            
            
            # Info about Trakt state
            trakt_info_str = f"Trakt: S{t_season}E{t_episode} | Date: {t_date_str}"
            
            # [Fix Mismatch] Check
            if fix_mismatch and item['type'] == 'show':
                # Compare Head Dates strict
                if r_date_str != "None" and t_date_str != "None":
                    if r_date_str != t_date_str:
                        # Allow 1 day variance? Or strict. Let's start strict.
                        print(f"{info} | [MISMATCH] {t_date_str} != {r_date_str} -> Marking for Forced Wipe")
                        force_wipe = True

            # Comparison Logic
            if item['type'] == 'show' and progress:
                h_season = progress['season']
                h_episode = progress['episode']
                
                # Check if Trakt is AHEAD
                # Note: We must toggle trakt_ahead flag BEFORE mismatch check
                if (t_season > h_season) or (t_season == h_season and t_episode > h_episode):
                    trakt_ahead = True
                    print(f"{info} | [{trakt_info_str}] | [TRAKT AHEAD] - Backfilling Date")
                    
                    # If Mismatch flag is ON, we force sync but do NOT wipe (unless future date? For now, trust Ahead)
                    # User wants to "update date" but keep progress.
                    if fix_mismatch and r_date_str != "None" and t_date_str != "None" and r_date_str != t_date_str:
                         print(f"   -> [MISMATCH] {t_date_str} != {r_date_str}. Treating as Backfill strictly.")
                         should_sync = True
                         # CRITICAL: Disable force_wipe to prevent removal logic from nuking history
                         force_wipe = False 
                    else:
                         should_sync = True
                         
                    scraper.cache.set_status(item['url'], 'completed')
                        
                elif (t_season == h_season) and (t_episode == h_episode):
                     # Progress Equal. Check Date?
                     dates_match = False
                     if t_date_dt and rezka_date:
                        dates_match = (t_date_dt.date() == rezka_date.date())
                     
                     if dates_match and not force_wipe:
                         print(f"{info} | [{trakt_info_str}] | [EQUAL] - Dates Match")
                         should_sync = False
                     else:
                         print(f"{info} | [{trakt_info_str}] | [DATE MISMATCH] -> {r_date_str}")
                         should_sync = True
                else:
                     # HDRezka Ahead
                     print(f"{info} | [{trakt_info_str}] | [SYNCING] - Progress Update")
                     
            else:
                # Movie logic
                dates_match = False
                if t_date_dt and rezka_date:
                    dates_match = (t_date_dt.date() == rezka_date.date())

                if dates_match:
                     print(f"{info} | [{trakt_info_str}] | [EQUAL] - Dates Match")
                     should_sync = False
                else:
                     print(f"{info} | [{trakt_info_str}] | [DATE MISMATCH] -> {r_date_str}")
                     should_sync = True
        else:
            print(f"{info} | [NEW] | [SYNCING]")

        if should_sync:
            final_sync_list.append(item)
            
            # Removal Logic:
            # We always remove the SPECIFIC item history before adding it (to prevent duplicates).
            # If Trakt is NOT ahead (Rezka is authority), we WIPE the show to ensure clean history/dates.
            # If Trakt IS ahead (Backfilling), we only remove the specific episode (Granular).
            
            wipe = False
            if item['type'] == 'show':
                if not trakt_ahead:
                    wipe = True
                if force_wipe:
                    wipe = True
            
            # Pass this intent to removal list
            # We clone item and add flag
            rem_item = item.copy()
            rem_item['wipe'] = wipe
            
            if imdb_id in trakt_watched and not resync:
                 items_to_remove.append(rem_item)

    print("-------------------------\n")

    # --- Phase 2: Batch Sync ---
    if not final_sync_list:
        print("Nothing to sync.")
        return

    print(f"\nPhase 2: Syncing {len(final_sync_list)} items to Trakt...")
    
    # Deduplicate final_sync_list by IMDb ID to prevent conflict (Double shows)
    # Strategy: Keep item with LATEST date.
    # This handles cases like 'Dan Da Dan' appearing as TV-1 and TV-2
    unique_map = {}
    for item in final_sync_list:
        mid = item.get('imdb_id') or item.get('ids', {}).get('imdb')
        if not mid: continue
        
        if mid not in unique_map:
            unique_map[mid] = item
        else:
            # Compare dates
            existing = unique_map[mid]
            d1 = existing.get('date')
            d2 = item.get('date')
            
            # If d2 > d1, replace
            # date is datetime object usually
            if d2 and d1:
                if d2 > d1:
                    unique_map[mid] = item
            elif d2 and not d1:
                    unique_map[mid] = item
                    
    final_sync_list = list(unique_map.values())
    if len(final_sync_list) < len(unique_map): # Wait, unique_map len is deduped len.
         pass # Check logic: len(final_sync_list) is new len.
         
    # Re-check len
    print(f"   Deduplicated to {len(final_sync_list)} unique items.")

    # Batch size of 100 (Trakt limit)
    batch_size = 100
    # 1. Handle Removals (for Updates or Forced Resync)
    removal_list = []
    if resync:
        print("   [Force Resync] Updating all synced items (clean slate)...")
        # For resync, we want to WIPE everything.
        # Create copies with wipe=True
        removal_list = []
        for it in final_sync_list:
            c = it.copy()
            c['wipe'] = True
            removal_list.append(c)
    else:
        if items_to_remove:
            print(f"   [Update] Clearing old history for {len(items_to_remove)} items to ensure correct dates...")
            removal_list = items_to_remove 
        
    if removal_list:
        print(f"Removing history for {len(removal_list)} items...")
        # Helper logging for GUI
        import sys
        import time
        r_chunks = [removal_list[i:i + batch_size] for i in range(0, len(removal_list), batch_size)]
        for chunk in tqdm(r_chunks, desc="Removing Old History", file=sys.stdout):
             if not dry_run:
                 trakt.remove_from_history_batch(chunk)
                 time.sleep(5) # Wait for Trakt to process removals
             else:
                 print(f"   [Dry Run] Would remove batch of {len(chunk)} items.")

    # 2. Add New History
    chunks = [final_sync_list[i:i + batch_size] for i in range(0, len(final_sync_list), batch_size)]
    
    total_synced = 0
    
    import sys
    for chunk in tqdm(chunks, desc="Batch Adding", file=sys.stdout):
        if not dry_run:
            result = trakt.add_to_history_batch(chunk)
            if result:
                added = result.get('added', {})
                movies = added.get('movies', 0)
                episodes = added.get('episodes', 0) 
                total_synced += movies + episodes
                
                # Check for rejected items
                nf = result.get('not_found', {})
                not_found_count = len(nf.get('movies', [])) + len(nf.get('shows', [])) + len(nf.get('episodes', []))
                if not_found_count > 0:
                    print(f"   [Trakt Warning] {not_found_count} items ignored by Trakt (Invalid ID/Not Found):")
                    for x in nf.get('movies', []):
                         print(f"      - Movie ID: {x.get('ids')}")
                    for x in nf.get('shows', []):
                         print(f"      - Show ID: {x.get('ids')}")
        else:
             print(f"   [Dry Run] Would add batch of {len(chunk)} items.")
             total_synced += len(chunk) # fake count for summary
        
    print(f"\nSync Complete!")
    print(f"Total Items Processed: {len(watch_list)}")
    print(f"Resolved IDs: {len(resolved_items)}")
    print(f"Items Added to History: {total_synced}")
    
    import time
    if failed_resolution:
        print("\nItems with no IMDB ID found:")
        for fail in failed_resolution:
            print(f"- {fail}")

    # --- Phase 3: Verification ---
    print("\n-------------------------")
    print("Phase 3: Verification")
    print("Waiting 5 seconds for Trakt propagation...")
    time.sleep(5)
    
    print("Re-fetching Trakt history...")
    # Re-fetch fresh state
    trakt_watched_new = trakt.get_watched_shows(load_progress=True)
    trakt_movies_new = trakt.get_watched_movies()
    if trakt_movies_new:
        trakt_watched_new.update(trakt_movies_new)
        
    print(f"Verifying {len(final_sync_list)} synced items...")
    
    mismatch_count = 0
    
    for item in final_sync_list:
        imdb_id = item['imdb_id']
        title = item['title']
        rezka_date = item['date']
        
        if imdb_id not in trakt_watched_new:
            print(f"[VERIFY FAIL] '{title}' ({imdb_id}) not found in Trakt history!")
            mismatch_count += 1
            continue
            
        t_item = trakt_watched_new[imdb_id]
        
        # Check Date
        t_last_watched = t_item.get('last_watched_at')
        t_date_dt = None
        if t_last_watched:
             try:
                t_date_dt = datetime.strptime(t_last_watched[:10], "%Y-%m-%d")
             except:
                pass
        
        dates_match = False
        if t_date_dt and rezka_date:
            dates_match = (t_date_dt.date() == rezka_date.date())
        elif t_date_dt is None and rezka_date is None:
            dates_match = True
            
        if not dates_match:
            r_str = rezka_date.strftime("%d-%m-%Y") if rezka_date else "None"
            t_str = t_date_dt.strftime("%d-%m-%Y") if t_date_dt else "None"
            
            verified_deep = False
            if item['type'] == 'show' and item.get('progress'):
                 prog = item['progress']
                 s_req = prog['season']
                 e_req = prog['episode']
                 
                 seasons = t_item.get('seasons', [])
                 found_ep_date = None
                 for sea in seasons:
                     if sea.get('number') == s_req:
                         for ep in sea.get('episodes', []):
                             if ep.get('number') == e_req:
                                 # Found episode
                                 ep_w = ep.get('last_watched_at')
                                 if ep_w:
                                      try:
                                        ed = datetime.strptime(ep_w[:10], "%Y-%m-%d")
                                        if rezka_date and ed.date() == rezka_date.date():
                                            verified_deep = True
                                            found_ep_date = ed
                                        else:
                                            found_ep_date = ed
                                      except: pass
                 
                 if verified_deep:
                     # print(f"[VERIFY OK] '{title}' (S{s_req}E{e_req}) date verified: {r_str}")
                     pass
                 else:
                     ep_date_str = found_ep_date.strftime("%d-%m-%Y") if found_ep_date else "None"
                     print(f"[VERIFY FAIL] '{title}' (S{s_req}E{e_req}) -> Expected: {r_str} | Found: {ep_date_str}")
                     mismatch_count += 1
            else:
                 # Movie or simple show match
                 print(f"[VERIFY FAIL] '{title}' -> Expected: {r_str} | Found: {t_str}")
                 mismatch_count += 1
        else:
            # print(f"[VERIFY OK] '{title}' date match: {r_str}")
            pass
            
    if mismatch_count == 0:
        print("\nAll items verified successfully!")
    else:
        print(f"\nVerification finished with {mismatch_count} mismatches. Check log.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync HDRezka history to Trakt")
    parser.add_argument('--resync', action='store_true', help='Force resync (remove items from Trakt history before adding). WARNING: Skips items where Trakt is ahead.')
    parser.add_argument('--headless', action='store_true', help='Run scraper in headless mode')
    parser.add_argument('--fix-duplicates', action='store_true', help='Scan and remove duplicate history entries')
    parser.add_argument('--fix-mismatch', action='store_true', help='Force wipe and resync if Trakt Last Watched Date does not match HDRezka')
    parser.add_argument('--dry-run', action='store_true', help='Simulate run without making changes to Trakt')
    
    args = parser.parse_args()
    
    start(resync=args.resync, headless=args.headless, fix_duplicates=args.fix_duplicates, fix_mismatch=args.fix_mismatch, dry_run=args.dry_run)

