import json
import shutil

cache_file = 'cache.json'
backup_file = 'cache.json.bak'

# Backup first
shutil.copy(cache_file, backup_file)

with open(cache_file, 'r', encoding='utf-8') as f:
    data = json.load(f)

updates = {
    'tt26748649': 'tt22091076', # High Potential
    'tt8232636': 'tt16867040'   # Cunk on Britain
}

count = 0
for url, item in data.items():
    if not isinstance(item, dict): continue
    
    current_id = item.get('id')
    
    # Check top level ID
    if current_id in updates:
        new_id = updates[current_id]
        print(f"Updating {url} | ID: {current_id} -> {new_id}")
        item['id'] = new_id
        
        # Check trakt_data
        t_data = item.get('trakt_data')
        if t_data and 'ids' in t_data:
             if t_data['ids'].get('imdb') == current_id:
                 t_data['ids']['imdb'] = new_id
                 # Clear other IDs to force Trakt to re-resolve/search if needed?
                 # Or just leave them? Trakt ID might be wrong.
                 # Let's clear trakt id to force re-lookup if we were using it?
                 # But we don't usually use trakt id for lookup unless we have it.
                 # If we have the wrong Trakt ID, it might still fail.
                 # User said "keep new ids".
                 # If we change IMDb ID, TraktSync uses IMDb ID to search/add.
                 # Safest is to remove 'trakt' ID from cache so it doesn't prioritize it?
                 # But `process_id_resolution` uses `trakt_data`.
                 # If we leave bad Trakt ID, `add_to_history` might use it.
                 # Let's invalid Trakt ID if we change IMDb ID.
                 if 'trakt' in t_data['ids']:
                     print(f"   Clearing potential bad Trakt ID: {t_data['ids']['trakt']}")
                     t_data['ids']['trakt'] = None
                     
        count += 1

print(f"Updated {count} items.")

with open(cache_file, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=4, ensure_ascii=False)
