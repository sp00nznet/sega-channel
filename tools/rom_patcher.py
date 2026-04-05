"""
Sega Channel ROM Patcher

Takes a Sega Channel menu ROM and patches the game/category entry titles
to create a custom game list. The ROM's display engine, graphics, and
animations are preserved — only the title text changes.

Entry table structure (in SCMENU data area, upper 1MB):
- Entries 0-9: Categories (100 bytes each, starting at $10050C)
- Entries 10-59: Games (variable size, starting at $1009D0)
- Each entry has a $041C $0308 marker followed by the title text

Usage:
    python rom_patcher.py --rom SegaChannel.bin --catalog patch_catalog.json --output SegaChannel_Patched.bin
"""

import struct
import json
import sys
import argparse
from pathlib import Path


def find_entries(rom):
    """Find all $0428 entries with their title locations."""
    marker_0428 = bytes([0x04, 0x28])
    marker_name = bytes([0x04, 0x1C, 0x03, 0x08])

    entries = []
    idx = 0x100000  # Start of SCMENU data area

    while True:
        idx = rom.find(marker_0428, idx, len(rom))
        if idx < 0:
            break

        # Find the name marker within this entry
        name_marker = rom.find(marker_name, idx, idx + 0x200)
        if name_marker < 0:
            idx += 2
            continue

        # Read the title
        title_start = name_marker + 4
        title_end = rom.find(b'\x00', title_start, title_start + 32)
        if title_end < 0:
            title_end = title_start + 24

        title = rom[title_start:title_end].decode('ascii', errors='replace').strip()

        # Calculate title field width (space for new title)
        # The title is padded to fill the field
        field_end = title_end
        while field_end < name_marker + 0x40 and rom[field_end] == 0x00:
            field_end += 1
        # But also check for the start of the next data (pointer pair $0010)
        for check in range(title_end, min(title_end + 8, len(rom)), 2):
            w = struct.unpack('>H', rom[check:check+2])[0]
            if w == 0x0010 or w == 0x0000:
                field_end = check
                break

        title_field_size = field_end - title_start

        entries.append({
            'offset': idx,
            'title_offset': title_start,
            'title_field_size': title_field_size,
            'title': title,
        })

        idx += 2

    return entries


def format_title(title, width, center=True):
    """Format a title to fit in a fixed-width field, space-padded."""
    title = title.strip()
    if len(title) > width:
        title = title[:width]

    if center:
        padding = (width - len(title)) // 2
        result = ' ' * padding + title + ' ' * (width - len(title) - padding)
    else:
        result = title + ' ' * (width - len(title))

    return result.encode('ascii', errors='replace')


def patch_rom(rom_data, catalog, entries):
    """Patch the ROM with new category and game titles."""
    rom = bytearray(rom_data)
    categories = catalog.get('categories', [])

    # Map the catalog to entries
    # Entries 0-9 are categories, 10-59 are games
    cat_entries = entries[:10]
    game_entries = entries[10:60]

    patches_applied = 0

    # Patch category titles
    for i, cat in enumerate(categories[:10]):
        if i >= len(cat_entries):
            break
        entry = cat_entries[i]
        new_title = format_title(cat['name'], entry['title_field_size'])
        offset = entry['title_offset']

        # Write the new title
        for j, b in enumerate(new_title):
            if offset + j < len(rom):
                rom[offset + j] = b

        patches_applied += 1
        print(f"  Cat [{i}] '{entry['title']}' -> '{cat['name']}'")

    # Patch game titles
    game_idx = 0
    for cat in categories:
        for game in cat.get('games', []):
            if game_idx >= len(game_entries):
                break
            entry = game_entries[game_idx]
            new_title = format_title(game['title'], entry['title_field_size'])
            offset = entry['title_offset']

            for j, b in enumerate(new_title):
                if offset + j < len(rom):
                    rom[offset + j] = b

            patches_applied += 1
            game_idx += 1

    print(f"\nPatched {patches_applied} entries ({len(categories)} categories + {game_idx} games)")
    return bytes(rom)


def generate_mapping(catalog):
    """Generate the sc_menu_game_map C array from the catalog."""
    # 10 categories (no server ID) + up to 50 games
    mapping = [0] * 10  # categories
    for cat in catalog.get('categories', []):
        for game in cat.get('games', []):
            mapping.append(game.get('server_id', 0))

    # Pad to 60
    while len(mapping) < 60:
        mapping.append(0)

    return mapping[:60]


def main():
    parser = argparse.ArgumentParser(description='Sega Channel ROM Patcher')
    parser.add_argument('--rom', required=True, help='Input ROM file')
    parser.add_argument('--catalog', required=True, help='Game catalog JSON')
    parser.add_argument('--output', required=True, help='Output patched ROM')
    parser.add_argument('--mapping', default=None, help='Output C mapping array')
    args = parser.parse_args()

    # Load ROM
    with open(args.rom, 'rb') as f:
        rom_data = f.read()
    print(f"Loaded ROM: {args.rom} ({len(rom_data)} bytes)")

    # Load catalog
    with open(args.catalog) as f:
        catalog = json.load(f)

    total_games = sum(len(c.get('games', [])) for c in catalog.get('categories', []))
    print(f"Catalog: {len(catalog['categories'])} categories, {total_games} games")

    # Find entries in ROM
    entries = find_entries(rom_data)
    print(f"Found {len(entries)} entries in ROM")
    print(f"  Categories: {len(entries[:10])}")
    print(f"  Games: {len(entries[10:60])}")
    print()

    # Patch
    patched = patch_rom(rom_data, catalog, entries)

    # Write output
    with open(args.output, 'wb') as f:
        f.write(patched)
    print(f"\nWrote: {args.output} ({len(patched)} bytes)")

    # Generate mapping
    mapping = generate_mapping(catalog)
    if args.mapping:
        with open(args.mapping, 'w') as f:
            f.write("/* Auto-generated SCMENU -> server ID mapping */\n")
            f.write("static const uint16 sc_menu_game_map[60] = {\n")
            f.write("  /* categories */\n  ")
            f.write(", ".join(f"{m:3d}" for m in mapping[:10]))
            f.write(",\n  /* games */\n")
            for row in range(10, 60, 10):
                chunk = mapping[row:row+10]
                f.write("  " + ", ".join(f"{m:3d}" for m in chunk))
                f.write(",\n" if row + 10 < 60 else "\n")
            f.write("};\n")
        print(f"Wrote mapping: {args.mapping}")
    else:
        print("\nMapping array:")
        print("  Categories: ", mapping[:10])
        print("  Games: ", mapping[10:])


if __name__ == '__main__':
    main()
