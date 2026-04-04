"""
SCMENU.BIN Category/Entry Record Decoder

From the analysis:
- Category names appear at ~91 byte intervals starting around offset 0x130
- The prefix 04 1C 03 08 appears 2 bytes before each category name
- Category entries have a repeating structure with embedded pointers

Let's decode the exact record format.
"""

import struct
import sys

def load(path):
    with open(path, 'rb') as f:
        return f.read()

def r32(d, o): return struct.unpack('>I', d[o:o+4])[0]
def r16(d, o): return struct.unpack('>H', d[o:o+2])[0]
def r8(d, o): return d[o]

def find_all(data, pattern):
    results = []
    idx = 0
    while True:
        idx = data.find(pattern, idx)
        if idx < 0: break
        results.append(idx)
        idx += 1
    return results

def main():
    f1 = "analysis/Sega Channel menu data/Sega Channel Guy/SCMENU.BIN"
    f2 = "analysis/Sega Channel menu data/Shorrock/from 1997V CD/SCMENU.BIN"

    data1 = load(f1)
    data2 = load(f2)

    # The sequence 04 1C 03 08 appears right before category name strings
    # Let's find all occurrences
    marker = bytes([0x04, 0x1C, 0x03, 0x08])

    print("=== CATEGORY MARKERS (04 1C 03 08) ===\n")
    for data, label in [(data1, "SCG"), (data2, "1997V")]:
        hits = find_all(data, marker)
        print(f"{label}: {len(hits)} occurrences")
        for h in hits:
            # After the marker, there should be the category name (null-padded)
            name_start = h + 4
            name_end = data.find(b'\x00', name_start, name_start + 32)
            if name_end < 0:
                name_end = name_start + 16
            name = data[name_start:name_end].decode('ascii', errors='replace').strip()
            print(f"  0x{h:06X}: \"{name}\"")
        print()

    # Now let's look at the FULL structure around each category
    # Walk backward from the marker to find the record start
    print("=== CATEGORY RECORD STRUCTURE ===\n")

    for data, label in [(data1, "SCG"), (data2, "1997V")]:
        print(f"--- {label} ---")
        hits = find_all(data, marker)

        for i, h in enumerate(hits[:6]):  # First 6 category entries
            name_start = h + 4
            name_end = data.find(b'\x00', name_start, name_start + 32)
            if name_end < 0: name_end = name_start + 16
            name = data[name_start:name_end].decode('ascii', errors='replace').strip()

            # The record likely starts with another pattern before it
            # From the hex dumps, 2 bytes before 04 1C we see: 03 B6
            # And before that we see: 00 00 00 00
            # Let's look at the full pattern leading up to this

            # Walk backward to find a recognizable record boundary
            # The pattern seems to be:
            #   XX XX  (some header)
            #   ...    (pointers/coordinates)
            #   03 B6  (constant)
            #   04 1C 03 08  (marker)
            #   "Name"  (null-terminated, padded)
            #   XX XX XX XX... (pointer list after name)

            # Look at bytes h-40 to h+60
            rec_start = h - 40
            if rec_start < 0: rec_start = 0

            print(f"\n  [{i}] \"{name}\" (marker at 0x{h:06X}):")

            # Decode the prefix structure
            # Going back from the marker, find the entry structure
            # From the hex dumps, the structure around each category entry is:
            #
            # +00: 04 28   (constant? $0428)
            # +02: 00 16 XX XX  (pointer to something in $16xxxx range)
            # +06: 03 08   (constant? $0308)
            # +08: 04 22   (constant? $0422)
            # +0A: 00 0X   (small number 0-3)
            # +0C: 02 E4   (constant)
            # +0E: 02 78   (constant)
            # +10: 00 10 XX XX  (pointer to $10xxxx - artwork/tiles?)
            # +14: 00 15 XX XX  (pointer to $15xxxx - some data)
            # +18: 00 00 00 00  (zeros)
            # +1C: 03 B6   (constant)
            # +1E: 04 22   (constant $0422)
            # +20: 00 0X   (small number 0-3)
            # +22: 02 E4   (constant)
            # +24: 02 78   (constant)
            # +26: 00 10 XX XX  (pointer to $10xxxx)
            # +2A: 00 15 XX XX  (pointer to $15xxxx)
            # +2E: 00 00 00 00  (zeros)
            # +32: 03 B6   (constant)
            # +34: 04 1C   (marker byte 1-2)
            # +36: 03 08   (marker byte 3-4)
            # +38: "Category Name" + padding
            # +48: pointers after name...

            # So the full category entry seems to be ~90-96 bytes
            # Let's look at what's right after the name
            name_padded_end = name_end
            # Pad to next even boundary
            while name_padded_end < len(data) and (name_padded_end - name_start) < 16 and data[name_padded_end] == 0:
                name_padded_end += 1

            # After the null-padded name, there are more pointers
            print(f"    Name bytes: {name_end - name_start} chars + {name_padded_end - name_end} padding")

            # Now let's look at what follows
            after_name = name_padded_end
            if after_name + 20 <= len(data):
                post_name = data[after_name:after_name+20]
                # These should be pointers ($0010xxxx range)
                ptrs = []
                for j in range(0, 20, 2):
                    if after_name + j + 2 <= len(data):
                        w = r16(data, after_name + j)
                        ptrs.append(f'{w:04X}')
                print(f"    Post-name words: {' '.join(ptrs)}")

            # Show the 0428-prefix structure
            # Search backward for 0428 pattern
            for back in range(2, 60, 2):
                if h - back >= 0:
                    w = r16(data, h - back)
                    if w == 0x0428:
                        entry_start = h - back
                        entry_len = after_name + 20 - entry_start
                        print(f"    Entry start: 0x{entry_start:06X} (0x0428 found {back} bytes before marker)")
                        print(f"    Entry length: ~{entry_len} bytes")

                        # Dump the full entry
                        for off in range(0, entry_len, 16):
                            chunk = data[entry_start+off:entry_start+off+16]
                            hex_str = ' '.join(f'{b:02X}' for b in chunk)
                            asc = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
                            print(f"      +{off:3d}: {hex_str:<48}  {asc}")
                        break

        print()

    # Now let's look at GAME entries (the text descriptions)
    # Game entries appear after the categories and have game titles
    print("=== GAME ENTRY SEARCH ===\n")

    # Find "Alien Storm" in SCG (first game title we saw at $484)
    for data, label in [(data1, "SCG")]:
        title = b'Alien Storm'
        offs = find_all(data, title)
        print(f"'{title.decode()}' found at: {[f'0x{o:06X}' for o in offs]}")

        if offs:
            first = offs[0]
            # Dump 80 bytes before and 160 bytes after
            start = max(0, first - 80)
            end = min(len(data), first + 160)
            print(f"\n  Context (0x{start:06X} - 0x{end:06X}):")
            for off in range(start, end, 16):
                chunk = data[off:off+16]
                hex_str = ' '.join(f'{b:02X}' for b in chunk)
                asc = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
                marker = " <--- TITLE" if off <= first < off + 16 else ""
                print(f"    {off:06X}: {hex_str:<48}  {asc}{marker}")

    # Find game description text that follows
    print("\n\nLooking for game descriptions near Alien Storm...")
    for data, label in [(data1, "SCG")]:
        # Search for description-like text after 0x484
        for scan in range(0x480, min(0x900, len(data))):
            chunk = data[scan:scan+60]
            text = chunk.decode('ascii', errors='replace')
            if len(text) > 10 and text[0].isalpha() and any(c.islower() for c in text[:20]):
                clean = ''.join(c if 32 <= ord(c) < 127 else '|' for c in text)
                print(f"  0x{scan:06X}: \"{clean[:60]}\"")
                break

    # Let's also check what the "Alien Storm" entry record looks like
    # The data at $434 starts with the first entry
    # We saw "Alien Storm" at offset $484
    # That's $484 - $434 = $50 (80) bytes into the main data section

    print("\n=== FIRST GAME ENTRY RECORD ($434) ===")
    for data, label in [(data1, "SCG"), (data2, "1997V")]:
        print(f"\n--- {label} ---")
        # Find first game title
        base = 0x434

        # Look for the title string - it starts with spaces
        for scan in range(base, base + 0x200):
            if data[scan:scan+2] == b'  ':
                # Check if followed by text
                end = data.find(b'\x00', scan, scan + 32)
                if end > 0:
                    title = data[scan:end].decode('ascii', errors='replace').strip()
                    if len(title) >= 4:
                        rec_offset = scan - base
                        print(f"  First title: \"{title}\" at file offset 0x{scan:06X} (record +0x{rec_offset:02X})")

                        # The record before the title ($434 to $484 = 0x50 bytes)
                        print(f"  Pre-title record (0x{rec_offset:02X} bytes):")
                        for off in range(0, rec_offset, 16):
                            chunk = data[base+off:base+off+16]
                            hex_str = ' '.join(f'{b:02X}' for b in chunk)
                            print(f"    +{off:3d}: {hex_str}")

                        # The title + post-title data
                        print(f"  Title + post-title:")
                        for off in range(rec_offset, min(rec_offset + 80, 256), 16):
                            chunk = data[base+off:base+off+16]
                            hex_str = ' '.join(f'{b:02X}' for b in chunk)
                            asc = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
                            print(f"    +{off:3d}: {hex_str:<48}  {asc}")
                        break
            if scan > base + 0x100:
                break

if __name__ == '__main__':
    main()
