"""
SCMENU.BIN Generator

Produces custom menu data from a game catalog. Uses an existing
SCMENU.BIN as a template — copies the fixed graphical/tile data
and rewrites the category and game entry tables.

Usage:
    python scmenu_build.py --template SCMENU.BIN --catalog games.json --output SCMENU_NEW.BIN

Catalog JSON format:
{
  "categories": [
    {
      "name": "The Arcade",
      "games": [
        {"id": 1, "title": "Sonic the Hedgehog 2"},
        {"id": 2, "title": "Streets of Rage 2"}
      ]
    },
    ...
  ]
}
"""

import struct
import json
import argparse
from pathlib import Path

# Constants from the format spec
ENTRY_HEADER = 0x0428
SUB_ENTRY = 0x0422
NAME_CMD = 0x041C
DISPLAY_PARAM = 0x0308
END_MARKER = 0x03B6
STD_X = 0x02E4
STD_Y = 0x0278

# Base address in Genesis address space
BASE_ADDR = 0x100000

# Fixed template regions we preserve
TEMPLATE_HEADER_SIZE = 0x34  # Fixed header fields


def write_word(buf, val):
    """Append a big-endian 16-bit word to buffer."""
    buf.extend(struct.pack('>H', val))

def write_long(buf, val):
    """Append a big-endian 32-bit long to buffer."""
    buf.extend(struct.pack('>I', val))

def write_padded_string(buf, text, total_len):
    """Write a null-terminated, space-padded string."""
    encoded = text.encode('ascii', errors='replace')
    if len(encoded) >= total_len:
        encoded = encoded[:total_len - 1]
    # Pad with spaces, then null
    padded = encoded + b'\x00'
    while len(padded) < total_len:
        padded += b'\x00'
    buf.extend(padded)

def format_title(name, width=24):
    """Center a title in a fixed-width field, space-padded."""
    name = name.strip()
    if len(name) >= width:
        return name[:width]
    padding = (width - len(name)) // 2
    return ' ' * padding + name + ' ' * (width - len(name) - padding)


class ScMenuBuilder:
    """Builds a SCMENU.BIN file from a catalog."""

    def __init__(self, template_path=None):
        self.template = None
        if template_path:
            with open(template_path, 'rb') as f:
                self.template = f.read()

        # Pointers we'll need to fix up
        self.tile_ptr_pool = []  # Reuse tile pointers from template
        self.palette_ptr_1 = 0x001545C8  # Default palette ptr (SCG)
        self.palette_ptr_2 = 0x001545D2  # Default palette ptr 2 (SCG)
        self.display_ptr = 0x0016B74C    # Default display ptr (SCG)

        if self.template:
            self._extract_template_ptrs()

    def _extract_template_ptrs(self):
        """Extract reusable pointers from the template file."""
        # Find palette/display pointers from the first category entry
        # Look for the $0428 marker
        marker = bytes([0x04, 0x28])
        idx = self.template.find(marker, 0x40)
        if idx >= 0 and idx + 20 < len(self.template):
            # Display ptr at +2 (32-bit)
            self.display_ptr = struct.unpack('>I', self.template[idx+2:idx+6])[0]
            # This is only 2 bytes — actually display_ptr is 2 words
            hi = struct.unpack('>H', self.template[idx+2:idx+4])[0]
            lo = struct.unpack('>H', self.template[idx+4:idx+6])[0]
            self.display_ptr = (hi << 16) | lo

        # Extract palette pointers from the template's first entry
        # They appear at offsets +$14 and +$28 from each entry
        idx2 = self.template.find(bytes([0x04, 0x22]), idx + 6)
        if idx2 >= 0 and idx2 + 14 < len(self.template):
            self.palette_ptr_1 = struct.unpack('>I', self.template[idx2+12:idx2+16])[0]

        # Extract tile pointer patterns for reuse
        # Scan template for $0010xxxx pointers in the entry area
        for i in range(0x40, min(0x400, len(self.template)), 2):
            val = struct.unpack('>I', self.template[i:i+4])[0]
            if 0x100500 <= val <= 0x10FFFF:
                if val not in self.tile_ptr_pool:
                    self.tile_ptr_pool.append(val)

    def build(self, catalog, output_path):
        """Build SCMENU.BIN from a catalog dictionary."""
        categories = catalog.get('categories', [])

        # Phase 1: Build the entry table (categories + games)
        entries_buf = bytearray()
        description_buf = bytearray()
        desc_base_offset = 0  # Will be fixed up later

        # Track where game descriptions will go
        game_desc_offsets = []

        # Build category entries
        for cat_idx, cat in enumerate(categories):
            cat_name = cat['name']
            games = cat.get('games', [])

            # Placeholder tile pointers (reuse from template pool)
            tile_idx = (cat_idx * 4) % max(len(self.tile_ptr_pool), 1)

            # Write category entry
            self._write_category_entry(entries_buf, cat_name, cat_idx)

        # Build game entries
        for cat_idx, cat in enumerate(categories):
            for game in cat.get('games', []):
                game_title = game['title']
                game_id = game.get('id', 0)

                # Track description offset
                desc_offset = len(description_buf)
                game_desc_offsets.append(desc_offset)

                # Write game description (simple English-only for now)
                desc_text = game.get('description', f'Play {game_title}!')
                description_buf.extend(desc_text.encode('ascii', errors='replace'))
                description_buf.extend(b'\x00')
                # Pad to even boundary
                if len(description_buf) % 2:
                    description_buf.extend(b'\x00')

                # Write game entry
                self._write_game_entry(entries_buf, game_title, game_id)

        # Phase 2: Assemble the full file
        output = bytearray()

        # Header: first 0x34 bytes
        if self.template:
            output.extend(self.template[0:TEMPLATE_HEADER_SIZE])
        else:
            # Minimal header
            output.extend(b'\x00' * TEMPLATE_HEADER_SIZE)

        # Fixed display constants ($0034-$003F)
        if self.template and len(self.template) >= 0x44:
            output.extend(self.template[0x34:0x44])
        else:
            output.extend(bytes([0x03, 0x14, 0x03, 0x6E, 0x00, 0x00,
                                 0x02, 0x24, 0x03, 0x0E, 0x04, 0x40,
                                 0x00, 0x16, 0x00, 0x15]))

        # Menu entry table (categories + games)
        # Pad to align entries at a known offset
        entries_start = 0x100  # Start entries at file offset $100
        while len(output) < entries_start:
            output.extend(b'\x00')

        output.extend(entries_buf)

        # Description text region
        desc_region_start = len(output)
        output.extend(description_buf)

        # If we have a template, append the graphical data from it
        # (tiles, palettes, icons — everything after the text data)
        if self.template:
            # Copy tile/graphic data from template starting at a safe offset
            gfx_start = 0x8000  # Graphics typically start deeper in the file
            if len(self.template) > gfx_start:
                while len(output) < gfx_start:
                    output.extend(b'\x00')
                output.extend(self.template[gfx_start:])

        # Fix up the main pointer at $0000
        main_ptr = BASE_ADDR + entries_start
        output[0:4] = struct.pack('>I', main_ptr)

        # Pad or trim to expected size
        target_size = 615028
        if len(output) < target_size:
            output.extend(b'\xFF' * (target_size - len(output)))
        elif len(output) > target_size:
            output = output[:target_size]

        with open(output_path, 'wb') as f:
            f.write(output)

        print(f"Generated {output_path} ({len(output)} bytes)")
        print(f"  {len(categories)} categories")
        total_games = sum(len(c.get('games', [])) for c in categories)
        print(f"  {total_games} games")

    def _write_category_entry(self, buf, name, index):
        """Write a single category entry to the buffer."""
        # $0428 header
        write_word(buf, ENTRY_HEADER)
        # Display pointer (2 words)
        write_word(buf, (self.display_ptr >> 16) & 0xFFFF)
        write_word(buf, self.display_ptr & 0xFFFF)
        # $0308
        write_word(buf, DISPLAY_PARAM)

        # Sub-entry 1 (unselected)
        write_word(buf, SUB_ENTRY)
        write_word(buf, 0x0002)  # Unselected variant
        write_word(buf, STD_X)
        write_word(buf, STD_Y)
        # Tile pointer (reuse from pool)
        tile = self.tile_ptr_pool[index * 2 % len(self.tile_ptr_pool)] if self.tile_ptr_pool else 0x100800
        write_long(buf, tile)
        # Palette pointer
        write_long(buf, self.palette_ptr_1)
        # Padding
        write_long(buf, 0x00000000)
        # End marker
        write_word(buf, END_MARKER)

        # Sub-entry 2 (selected)
        write_word(buf, SUB_ENTRY)
        write_word(buf, 0x0003)  # Selected variant
        write_word(buf, STD_X)
        write_word(buf, STD_Y)
        write_long(buf, tile)
        write_long(buf, self.palette_ptr_2 if self.palette_ptr_2 else self.palette_ptr_1)
        write_long(buf, 0x00000000)
        write_word(buf, END_MARKER)

        # Name command
        write_word(buf, NAME_CMD)
        write_word(buf, DISPLAY_PARAM)
        write_padded_string(buf, format_title(name, 16), 16)

        # Post-name tile pointers (5 pointers)
        for i in range(5):
            idx = (index * 5 + i) % len(self.tile_ptr_pool) if self.tile_ptr_pool else 0
            ptr = self.tile_ptr_pool[idx] if self.tile_ptr_pool else 0x100800 + i * 8
            write_long(buf, ptr)

        # Entry terminator
        write_word(buf, 0x0000)

    def _write_game_entry(self, buf, title, game_id):
        """Write a single game entry to the buffer."""
        # $0428 header
        write_word(buf, ENTRY_HEADER)
        write_word(buf, (self.display_ptr >> 16) & 0xFFFF)
        write_word(buf, self.display_ptr & 0xFFFF)
        write_word(buf, DISPLAY_PARAM)

        # Sub-entry 1 (unselected)
        write_word(buf, SUB_ENTRY)
        write_word(buf, 0x0000)
        write_word(buf, STD_X)
        write_word(buf, STD_Y)
        tile = self.tile_ptr_pool[0] if self.tile_ptr_pool else 0x100800
        write_long(buf, tile)
        write_long(buf, self.palette_ptr_1)
        write_long(buf, 0x00000000)
        write_word(buf, END_MARKER)

        # Sub-entry 2 (selected)
        write_word(buf, SUB_ENTRY)
        write_word(buf, 0x0001)
        write_word(buf, STD_X)
        write_word(buf, STD_Y)
        write_long(buf, tile)
        write_long(buf, self.palette_ptr_2 if self.palette_ptr_2 else self.palette_ptr_1)
        write_long(buf, 0x00000000)
        write_word(buf, END_MARKER)

        # Name command
        write_word(buf, NAME_CMD)
        write_word(buf, DISPLAY_PARAM)
        write_padded_string(buf, format_title(title, 24), 24)

        # Post-name pointers (5 pointers: tiles + description + expanded)
        for i in range(5):
            idx = i % len(self.tile_ptr_pool) if self.tile_ptr_pool else 0
            ptr = self.tile_ptr_pool[idx] if self.tile_ptr_pool else 0x100800 + i * 8
            write_long(buf, ptr)

        # Game ID / flags
        write_word(buf, game_id & 0xFFFF)
        write_word(buf, 0x0000)


def main():
    parser = argparse.ArgumentParser(description='SCMENU.BIN Generator')
    parser.add_argument('--template', type=str, required=True,
                        help='Path to template SCMENU.BIN file')
    parser.add_argument('--catalog', type=str, required=True,
                        help='Path to game catalog JSON file')
    parser.add_argument('--output', type=str, default='SCMENU_NEW.BIN',
                        help='Output file path')
    args = parser.parse_args()

    with open(args.catalog) as f:
        catalog = json.load(f)

    builder = ScMenuBuilder(args.template)
    builder.build(catalog, args.output)


if __name__ == '__main__':
    main()
