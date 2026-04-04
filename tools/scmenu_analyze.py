"""
SCMENU.BIN Format Analyzer

Compares two SCMENU.BIN files to map the data format.
These are menu data files loaded at runtime address $100000 in the
Sega Channel adapter's DRAM.

The menu ROM calculates entry count as:
    entries = ($FF8400 - $100000) / $F6

Each entry is 246 ($F6) bytes. But the file also has a header and
other structures. Let's map it all.
"""

import struct
import sys
from collections import defaultdict

def load(path):
    with open(path, 'rb') as f:
        return f.read()

def read_long(data, offset):
    return struct.unpack('>I', data[offset:offset+4])[0]

def read_word(data, offset):
    return struct.unpack('>H', data[offset:offset+2])[0]

def find_strings(data, offset, length, min_len=4):
    """Find ASCII strings in a region."""
    strings = []
    current = b''
    start = 0
    for i in range(offset, min(offset + length, len(data))):
        b = data[i]
        if 0x20 <= b < 0x7F:
            if not current:
                start = i
            current += bytes([b])
        else:
            if len(current) >= min_len:
                strings.append((start, current.decode('ascii')))
            current = b''
    if len(current) >= min_len:
        strings.append((start, current.decode('ascii')))
    return strings

def analyze_header(data, label):
    """Analyze the SCMENU.BIN header structure."""
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"  File size: {len(data)} bytes (0x{len(data):06X})")
    print(f"{'='*70}")

    # First few longwords - likely pointers (relative to $100000 base)
    print("\n--- Header (first 64 bytes) ---")
    for i in range(0, 64, 4):
        val = read_long(data, i)
        # Check if it looks like a pointer (in $100000-$1FFFFF range)
        if 0x100000 <= val <= 0x200000:
            file_offset = val - 0x100000
            print(f"  +0x{i:04X}: 0x{val:08X}  → file offset 0x{file_offset:06X}")
        else:
            print(f"  +0x{i:04X}: 0x{val:08X}")

    # The first pointer should tell us where the main data starts
    first_ptr = read_long(data, 0)
    if 0x100000 <= first_ptr <= 0x200000:
        main_offset = first_ptr - 0x100000
        print(f"\n  Main data structure at file offset 0x{main_offset:06X}")

def analyze_structure(data, label):
    """Deep structural analysis of SCMENU.BIN."""
    print(f"\n--- Pointer Table Analysis ({label}) ---")

    # Scan for all values that look like $10xxxx pointers
    pointers = []
    for i in range(0, min(0x1000, len(data)), 2):
        val = read_long(data, i) if i + 4 <= len(data) else 0
        if 0x100000 <= val <= 0x100000 + len(data):
            pointers.append((i, val, val - 0x100000))

    print(f"  Found {len(pointers)} pointer-like values in first 4KB:")
    for offset, ptr, file_off in pointers[:30]:
        # Show what's at the target
        if file_off < len(data):
            sample = data[file_off:file_off+20]
            ascii_sample = ''.join(chr(b) if 32 <= b < 127 else '.' for b in sample)
            print(f"    +0x{offset:04X}: 0x{ptr:08X} → [0x{file_off:06X}] {sample.hex()[:24]}  '{ascii_sample[:20]}'")

    # Look at the data at $434 (pointed to by the first longword)
    print(f"\n--- Data at offset $0434 (main structure) ---")
    for i in range(0x434, min(0x600, len(data)), 2):
        val = read_word(data, i)
        if i < 0x434 + 64:
            long_val = read_long(data, i) if i + 4 <= len(data) else 0
            if 0x100000 <= long_val <= 0x200000:
                target = long_val - 0x100000
                print(f"    +0x{i:04X}: 0x{long_val:08X} → file 0x{target:06X}")

    # Entry size analysis
    # The menu ROM divides data size by $F6 (246) to get entry count
    # Let's see if we can find 246-byte record boundaries
    print(f"\n--- Record Boundary Analysis (246-byte records) ---")
    record_size = 0xF6  # 246 bytes

    # The records likely start after the header/pointer table
    # Try starting from different offsets to find alignment
    for start_offset in [0x434, 0x500, 0x530, 0x558, 0x580]:
        # Check if strings appear at regular intervals
        found_titles = 0
        for rec in range(0, 10):
            rec_start = start_offset + (rec * record_size)
            if rec_start + record_size > len(data):
                break
            strings = find_strings(data, rec_start, record_size, 3)
            if strings:
                found_titles += 1
        if found_titles >= 3:
            print(f"  Start 0x{start_offset:04X}: {found_titles}/10 records have strings - LIKELY")
        else:
            print(f"  Start 0x{start_offset:04X}: {found_titles}/10 records have strings")

def analyze_records(data, label, start_offset=None):
    """Analyze individual records."""
    record_size = 0xF6  # 246 bytes

    if start_offset is None:
        # Try to determine start offset by looking for string patterns
        # The categories like "The Arcade", "Sports Arena" etc appear in the data
        for test_off in range(0, 0x1000):
            sample = data[test_off:test_off+20]
            text = sample.decode('ascii', errors='replace')
            if any(cat in text for cat in ['The Arcade', 'Arcade', 'Sports', 'Family', 'Strategy']):
                print(f"  Found category text at 0x{test_off:04X}: {text.strip()}")

    # Let's just dump all strings to understand the layout
    print(f"\n--- All strings in file ({label}) ---")
    strings = find_strings(data, 0, len(data), 6)
    for offset, s in strings:
        # Categorize
        cat = ""
        if any(x in s for x in ['Arcade', 'Sports', 'Family', 'Strategy', 'Dungeon', 'Speedway', 'Ring', 'Wheels']):
            cat = " [CATEGORY]"
        elif any(x in s for x in ['SEGA', 'Sega', 'Copyright', 'TM']):
            cat = " [META]"
        elif len(s) > 10 and any(x in s.lower() for x in ['game', 'play', 'action', 'battle', 'fight', 'race', 'world']):
            cat = " [DESC?]"
        print(f"  0x{offset:06X}: \"{s}\"{cat}")

def diff_files(data1, data2):
    """Compare two SCMENU.BIN files to identify variable vs fixed regions."""
    print(f"\n{'='*70}")
    print(f"  DIFF ANALYSIS")
    print(f"{'='*70}")

    if len(data1) != len(data2):
        print(f"  Files are different sizes: {len(data1)} vs {len(data2)}")
        return

    # Find identical and different regions
    same_count = 0
    diff_count = 0
    regions = []  # (start, length, type) where type = 'same' or 'diff'
    current_type = None
    region_start = 0

    for i in range(len(data1)):
        is_same = data1[i] == data2[i]
        t = 'same' if is_same else 'diff'
        if t != current_type:
            if current_type is not None:
                regions.append((region_start, i - region_start, current_type))
            current_type = t
            region_start = i
        if is_same:
            same_count += 1
        else:
            diff_count += 1

    if current_type is not None:
        regions.append((region_start, len(data1) - region_start, current_type))

    pct_same = same_count / len(data1) * 100
    print(f"  Identical bytes: {same_count} ({pct_same:.1f}%)")
    print(f"  Different bytes: {diff_count} ({100-pct_same:.1f}%)")
    print(f"  Regions: {len(regions)}")

    # Show the first portion of same/diff map
    print(f"\n--- Region Map (first 100 regions) ---")
    for i, (start, length, rtype) in enumerate(regions[:100]):
        marker = "====" if rtype == 'same' else "DIFF"
        # Show content sample for diff regions
        sample = ""
        if rtype == 'diff' and length >= 4:
            s1 = find_strings(data1, start, min(length, 60), 3)
            s2 = find_strings(data2, start, min(length, 60), 3)
            if s1:
                sample = f"  file1: \"{s1[0][1][:40]}\""
            if s2:
                sample += f"  file2: \"{s2[0][1][:40]}\""
        elif rtype == 'same' and length >= 4:
            s = find_strings(data1, start, min(length, 60), 3)
            if s:
                sample = f"  \"{s[0][1][:40]}\""

        print(f"  0x{start:06X} +{length:5d}  [{marker}]{sample}")

    # Identify fixed header region
    # Find where the first difference occurs
    first_diff = next((r[0] for r in regions if r[1] > 0 and r[2] == 'diff'), None)
    if first_diff is not None:
        print(f"\n  First difference at offset 0x{first_diff:06X}")
        print(f"  Header (identical region): 0x0000 - 0x{first_diff:04X} ({first_diff} bytes)")

    return regions

def analyze_pointer_table(data, label):
    """Analyze the pointer/index table structure."""
    print(f"\n{'='*70}")
    print(f"  POINTER TABLE DEEP DIVE ({label})")
    print(f"{'='*70}")

    # The first longword is 0x00100434
    first_ptr = read_long(data, 0)
    print(f"  First pointer: 0x{first_ptr:08X}")

    # At offset $434, let's look at the structure more carefully
    # It likely contains pointers to category structures
    base = 0x434
    print(f"\n  Data at $434 (category/menu structure):")

    # Scan for a table of pointers
    for i in range(0, 256, 4):
        val = read_long(data, base + i)
        if val == 0:
            print(f"    +{i:3d} (0x{base+i:04X}): 0x{val:08X}  (end marker?)")
            break
        elif 0x100000 <= val <= 0x200000:
            target = val - 0x100000
            # Peek at target
            if target < len(data):
                peek = data[target:target+32]
                text = ''.join(chr(b) if 32 <= b < 127 else '.' for b in peek)
                print(f"    +{i:3d} (0x{base+i:04X}): 0x{val:08X} → 0x{target:06X} \"{text}\"")
        else:
            print(f"    +{i:3d} (0x{base+i:04X}): 0x{val:08X}")

def main():
    file1 = "analysis/Sega Channel menu data/Sega Channel Guy/SCMENU.BIN"
    file2 = "analysis/Sega Channel menu data/Shorrock/from 1997V CD/SCMENU.BIN"

    data1 = load(file1)
    data2 = load(file2)

    analyze_header(data1, "SCMENU.BIN (Sega Channel Guy)")
    analyze_header(data2, "SCMENU.BIN (Shorrock 1997V)")

    analyze_pointer_table(data1, "SCG")
    analyze_pointer_table(data2, "1997V")

    diff_files(data1, data2)

    # Now dump category strings from both
    print(f"\n{'='*70}")
    print(f"  CATEGORY / TITLE STRINGS COMPARISON")
    print(f"{'='*70}")
    for fname, data, label in [(file1, data1, "SCG"), (file2, data2, "1997V")]:
        print(f"\n  --- {label} ---")
        strings = find_strings(data, 0, len(data), 4)
        seen_cats = set()
        for offset, s in strings:
            s_stripped = s.strip()
            if not s_stripped:
                continue
            # Show unique meaningful strings
            if len(s_stripped) >= 4 and s_stripped not in seen_cats:
                # Only show first occurrence and if looks like a title/category
                if any(c.isupper() for c in s_stripped[:3]) or s_stripped[0] == ' ':
                    seen_cats.add(s_stripped)

        # Print categorized
        categories = [s for s in seen_cats if any(x in s for x in ['Arcade', 'Sports', 'Family', 'Strategy', 'Dungeon', 'Speedway', 'Ring', 'Wheels', 'Arena', 'Prize', 'Info', 'Guide', 'Test', 'Room'])]
        game_titles = [s for s in seen_cats if len(s) > 3 and s not in categories and not any(x in s.lower() for x in ['the ', 'and ', 'your ', 'this ', 'with ', 'from ', 'that ', 'have ', 'will '])]

        print(f"    Categories: {sorted(categories)}")
        print(f"    Potential game titles ({len(game_titles)}):")
        for t in sorted(game_titles)[:30]:
            print(f"      {t}")

if __name__ == '__main__':
    main()
