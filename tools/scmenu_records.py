"""
SCMENU.BIN Record Structure Mapper

Focus on finding the exact record layout by examining the data
around category names and game descriptions.
"""

import struct
import sys

def load(path):
    with open(path, 'rb') as f:
        return f.read()

def read_long(d, o):
    return struct.unpack('>I', d[o:o+4])[0]

def read_word(d, o):
    return struct.unpack('>H', d[o:o+2])[0]

def find_text(data, text):
    """Find all occurrences of text in data."""
    results = []
    encoded = text.encode('ascii')
    idx = 0
    while True:
        idx = data.find(encoded, idx)
        if idx < 0:
            break
        results.append(idx)
        idx += 1
    return results

def hex_dump(data, offset, length, width=16):
    """Pretty hex dump of a data region."""
    for i in range(0, length, width):
        addr = offset + i
        chunk = data[offset+i:offset+i+width]
        hex_str = ' '.join(f'{b:02X}' for b in chunk)
        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        print(f'    {addr:06X}: {hex_str:<{width*3}}  {ascii_str}')

def main():
    f1 = "analysis/Sega Channel menu data/Sega Channel Guy/SCMENU.BIN"
    f2 = "analysis/Sega Channel menu data/Shorrock/from 1997V CD/SCMENU.BIN"

    data1 = load(f1)
    data2 = load(f2)

    # First: find where category names appear
    print("=== LOCATING CATEGORY NAMES ===\n")

    categories_1 = ['The Arcade', 'Strategy Room', 'Family Room', 'Sports Arena', 'The Speedway', 'Info Pit', 'Game Guide']
    categories_2 = ['The Arcade', 'The Dungeon', 'Family Room', 'Sports Arena', "Wings 'N Wheels", "The King's Ring", 'Info Pit', 'Game Guide', 'Prize-O-Rama']

    print("File 1 (SCG):")
    for cat in categories_1:
        offsets = find_text(data1, cat)
        if offsets:
            print(f"  '{cat}' at offsets: {[f'0x{o:06X}' for o in offsets[:5]]}")

    print("\nFile 2 (1997V):")
    for cat in categories_2:
        offsets = find_text(data2, cat)
        if offsets:
            print(f"  '{cat}' at offsets: {[f'0x{o:06X}' for o in offsets[:5]]}")

    # Now examine the header structure more carefully
    # We know the first pointer is at offset 0 → $100434
    # The second pointer differs between files: $1004C4 vs $1004E4
    print("\n\n=== HEADER STRUCTURE DEEP DIVE ===")

    for data, label in [(data1, "SCG"), (data2, "1997V")]:
        print(f"\n--- {label} ---")
        ptr0 = read_long(data, 0x00) - 0x100000  # Main structure ptr
        ptr1 = read_long(data, 0x04) - 0x100000  # Second ptr
        ptr2 = read_long(data, 0x08) - 0x100000  # Third ptr

        print(f"  Ptr 0 (main):     0x{ptr0:06X}")
        print(f"  Ptr 1:            0x{ptr1:06X}")
        print(f"  Ptr 2:            0x{ptr2:06X}")

        # Bytes 0x0C-0x13: counts/flags
        print(f"  Bytes 0x0C-0x13:  {data[0x0C:0x14].hex()}")

        # The region between 0x14 and 0x34 is zeros in both files
        # 0x34 onwards has data
        print(f"  Bytes 0x34-0x43:  {data[0x34:0x44].hex()}")

        # Now look at what's BETWEEN the header and $434
        # This region (0x14 to 0x434) likely contains the menu structure
        # (category descriptors, pointers to game lists, etc.)

        # The data from ~0x43 has small structures
        # Let's look for repeating patterns
        print(f"\n  Region 0x0040-0x0100 (category descriptors?):")
        hex_dump(data, 0x40, 0xC0)

        # Now look at what's at ptr0 ($434)
        print(f"\n  Data at ptr0 (0x{ptr0:04X}):")
        hex_dump(data, ptr0, 0x60)

        # And at ptr1
        print(f"\n  Data at ptr1 (0x{ptr1:04X}):")
        hex_dump(data, ptr1, 0x30)

        # And ptr2
        print(f"\n  Data at ptr2 (0x{ptr2:04X}):")
        hex_dump(data, ptr2, 0x30)

    # Now let's look at the area right before and around the first category name
    print("\n\n=== AREA AROUND FIRST CATEGORY NAME ===")
    for data, label in [(data1, "SCG"), (data2, "1997V")]:
        cat_name = 'The Arcade'
        offsets = find_text(data, cat_name)
        if offsets:
            first = offsets[0]
            print(f"\n--- {label}: '{cat_name}' at 0x{first:06X} ---")
            # Show 32 bytes before and 64 bytes after
            start = max(0, first - 48)
            hex_dump(data, start, 112)

    # Look at the structure between categories
    print("\n\n=== INTER-CATEGORY STRUCTURE ===")
    for data, label in [(data1, "SCG"), (data2, "1997V")]:
        print(f"\n--- {label} ---")
        # Find all category positions
        all_cats = ['The Arcade', 'Strategy Room', 'Family Room', 'Sports Arena',
                    'The Speedway', 'The Dungeon', 'Info Pit', 'Game Guide',
                    "Wings 'N Wheels", "The King's Ring", 'Prize-O-Rama']
        cat_positions = []
        for cat in all_cats:
            offs = find_text(data, cat)
            if offs:
                cat_positions.append((offs[0], cat))

        cat_positions.sort()
        for i, (off, name) in enumerate(cat_positions):
            next_off = cat_positions[i+1][0] if i+1 < len(cat_positions) else off + 256
            gap = next_off - off
            print(f"  0x{off:06X}: '{name}' (gap to next: {gap} bytes / 0x{gap:X})")

    # Let's examine what the 0x0C-0x13 bytes mean
    # SCG:   04 09 12 04 02 03 06 03
    # 1997V: 03 0C 12 03 02 04 08 04
    print("\n\n=== HEADER FIELD ANALYSIS (0x0C-0x13) ===")
    print("SCG:   ", ' '.join(f'{b:02X}' for b in data1[0x0C:0x14]))
    print("1997V: ", ' '.join(f'{b:02X}' for b in data2[0x0C:0x14]))
    print("\nSCG categories: The Arcade, Strategy Room, Family Room, Sports Arena, The Speedway, Info Pit")
    print("  → 6 categories visible (04+02=6? or 09+12+04+02+03+06+03 = game counts?)")
    print("1997V categories: The Arcade, The Dungeon, Family Room, Sports Arena, Wings 'N Wheels, The King's Ring, Info Pit, Prize-O-Rama")
    print("  → 8 categories visible (03+0C+12+03+02+04+08+04 = game counts?)")

    # Count byte at 0x0C might be the number of categories
    # SCG: 0x04 = 4? But has 6+ categories
    # 1997V: 0x03 = 3? But has 8 categories
    # Not a simple count

    # Let's examine the record structure at $434 more carefully
    # The menu ROM at $600C does:
    #   move.l $8400.w, d0       ; end of data
    #   subi.l #$100000, d0      ; subtract base
    #   divu.w #$f6, d0          ; divide by 246
    # This gives the number of $F6-byte records
    # But the total file is 615028 bytes. 615028 / 246 = 2500.1
    # If records start at $434: (615028 - 0x434) / 246 = 2495.7
    # Not exact. The $F6 division may not apply to the whole file.

    # Actually, looking at the ROM code again:
    # $FF8400 = end of loaded data pointer (ROM size)
    # The code subtracts $100000 and divides by $F6
    # But $FF8400 for a 2MB menu ROM = $200000
    # ($200000 - $100000) / $F6 = $100000 / 246 = 4162.6
    # That's also not a round number...

    # Let me look at this from a different angle.
    # The SCMENU data starts at $100000. The ROM code accesses it
    # at various offsets. Let's see what offsets the ROM uses.

    print("\n\n=== FILE LAYOUT ESTIMATE ===")
    print(f"  Total file size: {len(data1)} bytes")
    print(f"  Header: 0x0000 - 0x0433 ({0x434} bytes)")
    print(f"  Main data: 0x0434 - end")

    # The $100430 reference in the ROM code (lea $100430, a0)
    # This is file offset 0x430 — right before $434!
    # The ROM does: move.l (a0, d0.w), d0
    # This reads a 32-bit value from a table at $100430 + d0
    # d0 = game_id * 4 (lsl.w #2, d0)
    # So $100430 is a table of 32-bit pointers indexed by game ID!

    print(f"\n  Game pointer table at 0x0430:")
    print(f"  (indexed by game_id * 4)")
    for data, label in [(data1, "SCG"), (data2, "1997V")]:
        print(f"\n  --- {label} ---")
        for i in range(0, 40, 4):
            val = read_long(data, 0x430 + i)
            if 0x100000 <= val <= 0x200000:
                target = val - 0x100000
                peek = data[target:target+24] if target < len(data) else b''
                text = ''.join(chr(b) if 32 <= b < 127 else '.' for b in peek)
                print(f"    [{i//4:2d}] 0x{val:08X} → 0x{target:06X} \"{text}\"")
            elif val == 0:
                print(f"    [{i//4:2d}] 0x{val:08X}  (null)")
            else:
                print(f"    [{i//4:2d}] 0x{val:08X}")

if __name__ == '__main__':
    main()
