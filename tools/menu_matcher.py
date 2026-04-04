"""
Match Sega Channel menu game entries to ROM files in the server library.

Extracts game titles from a menu ROM dump, then fuzzy-matches them against
the server's ROM library to create a mapping file.
"""

import struct
import json
import sys
import os
import urllib.request
from difflib import SequenceMatcher

def extract_menu_games(rom_path):
    """Extract game and category names from a Sega Channel menu ROM."""
    with open(rom_path, 'rb') as f:
        data = f.read()

    marker = bytes([0x04, 0x1C, 0x03, 0x08])

    # Scan the data portion (upper 1MB for 2MB ROMs)
    scan_start = 0x100000 if len(data) > 0x100000 else 0

    cat_names = {'Test Drives', 'The Arcade', 'Puzzlers', 'Family Room', 'Sports Arena',
                 'The Stadium', "Wings 'N Wheels", 'The Dungeon', 'News Link', 'Game Guide',
                 'Strategy Room', 'Info Pit', 'The Speedway', 'Prize-O-Rama', "The King's Ring",
                 'Digital Spotlight', 'Cheater! Cheater!', 'Trivial Trivia', 'How To Reach Us!',
                 'Enter Now', 'Legal stuff', 'We won!', 'The question'}

    idx = scan_start
    categories = []
    games = []

    while True:
        idx = data.find(marker, idx)
        if idx < 0:
            break
        name_start = idx + 4
        name_end = data.find(b'\x00', name_start, name_start + 32)
        if name_end < 0:
            name_end = name_start + 24
        name = data[name_start:name_end].decode('ascii', errors='replace').strip()
        if name and len(name) >= 3:
            if name in cat_names:
                categories.append(name)
            else:
                # Skip numbered entries like "1. Virtua Fighter 2"
                clean = name.lstrip('0123456789. ')
                if clean and len(clean) >= 3:
                    games.append(clean)
        idx += 1

    return categories, games


def fetch_server_catalog(host='127.0.0.1', port=8080):
    """Fetch the game catalog from the server API."""
    url = f'http://{host}:{port}/api/games'
    resp = urllib.request.urlopen(url)
    return json.loads(resp.read())


def normalize(s):
    """Normalize a string for comparison."""
    s = s.lower().strip()
    # Remove common suffixes/prefixes
    for remove in ['(usa)', '(europe)', '(world)', '(usa, europe)', '(en,fr,de,es)',
                   '(en,fr,de)', '(en,ja)', '(unl)', '- ', '_ ']:
        s = s.replace(remove, '')
    # Remove punctuation
    for ch in "!:'-.,()[]{}\"":
        s = s.replace(ch, '')
    # Collapse whitespace
    return ' '.join(s.split())


def match_score(menu_name, server_name):
    """Score how well a menu name matches a server name. Higher = better."""
    mn = normalize(menu_name)
    sn = normalize(server_name)

    # Exact match
    if mn == sn:
        return 1.0

    # One contains the other
    if mn in sn or sn in mn:
        return 0.9

    # Check if all significant words from menu name appear in server name
    menu_words = set(w for w in mn.split() if len(w) > 2)
    server_words = set(w for w in sn.split() if len(w) > 2)
    if menu_words and menu_words.issubset(server_words):
        return 0.85

    # Sequence matcher
    ratio = SequenceMatcher(None, mn, sn).ratio()
    return ratio


def match_games(menu_games, server_catalog, threshold=0.55):
    """Match menu games to server catalog entries."""
    matches = []
    unmatched = []

    for menu_name in menu_games:
        best_score = 0
        best_match = None

        for sg in server_catalog:
            score = match_score(menu_name, sg['title'])
            if score > best_score:
                best_score = score
                best_match = sg

        if best_score >= threshold and best_match:
            matches.append({
                'menu_title': menu_name,
                'server_id': best_match['id'],
                'server_title': best_match['title'],
                'score': round(best_score, 3),
                'size': best_match['size'],
            })
        else:
            unmatched.append({
                'menu_title': menu_name,
                'best_guess': best_match['title'] if best_match else '?',
                'best_score': round(best_score, 3),
            })

    return matches, unmatched


def main():
    rom_path = sys.argv[1] if len(sys.argv) > 1 else \
        "analysis/Sega Channel menu data/Sega Channel Guy/Canada Menu Demo December 1995.BIN"

    server_host = os.environ.get('SC_SERVER_HOST', '127.0.0.1')
    server_port = int(os.environ.get('SC_WEB_PORT', '8080'))

    print(f"Extracting games from: {rom_path}")
    categories, games = extract_menu_games(rom_path)

    print(f"\nCategories ({len(categories)}):")
    for c in categories:
        print(f"  {c}")

    print(f"\nGames ({len(games)}):")
    for g in games:
        print(f"  {g}")

    print(f"\nFetching server catalog from {server_host}:{server_port}...")
    try:
        catalog = fetch_server_catalog(server_host, server_port)
    except Exception as e:
        print(f"ERROR: Could not reach server: {e}")
        print("Make sure the web UI is running (python web_app.py --auto-start)")
        sys.exit(1)

    print(f"Server has {len(catalog)} games\n")

    matches, unmatched = match_games(games, catalog)

    print(f"MATCHED ({len(matches)}/{len(games)}):")
    for m in matches:
        conf = "***" if m['score'] >= 0.85 else "  ?" if m['score'] < 0.65 else "   "
        print(f"  {conf} {m['menu_title']:30s} -> [{m['server_id']:3d}] {m['server_title'][:40]} ({m['score']})")

    print(f"\nUNMATCHED ({len(unmatched)}):")
    for u in unmatched:
        print(f"      {u['menu_title']:30s}    best: {u['best_guess'][:30]} ({u['best_score']})")

    # Output mapping JSON
    mapping = {
        'rom_file': os.path.basename(rom_path),
        'categories': categories,
        'game_mapping': [
            {'menu_title': m['menu_title'], 'server_id': m['server_id'], 'server_title': m['server_title']}
            for m in matches if m['score'] >= 0.6
        ],
        'unmatched': [u['menu_title'] for u in unmatched],
    }

    out_path = os.path.splitext(os.path.basename(rom_path))[0] + '_mapping.json'
    with open(out_path, 'w') as f:
        json.dump(mapping, f, indent=2)
    print(f"\nMapping saved to: {out_path}")


if __name__ == '__main__':
    main()
