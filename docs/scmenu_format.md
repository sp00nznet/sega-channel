# SCMENU.BIN Data Format Specification

**File size:** 615,028 bytes (consistent across known dumps)  
**Runtime base address:** $100000 in Genesis address space  
**All pointers are absolute** (add $100000 to file offset)

---

## File Layout

```
Offset    Size    Description
------    ----    -----------
$0000     4       Ptr to main data entry point ($100434 in both files)
$0004     4       Ptr to secondary data (varies per month)
$0008     4       Ptr to tertiary data (varies per month)
$000C     8       Header fields (game/category counts, flags)
$0014     32      Zeros (reserved)
$0034     varies  VDP/display constants (partially fixed)
$0040     ~1012   Menu entry table (category + game entries)
$0434     varies  Main data section start (first game entry body)
...
$096274           End of file
```

## Header ($0000-$0013)

| Offset | Size | Description |
|--------|------|-------------|
| $0000 | Long | Ptr to main data ($100434 in both files) |
| $0004 | Long | Ptr to first category's display data |
| $0008 | Long | Ptr to category icon/tile data |
| $000C | 8 bytes | Monthly content descriptor (counts per category?) |
| $0014 | 32 bytes | All zeros (reserved) |
| $0034 | 12 bytes | VDP display parameters (constant between files) |

Bytes $0034-$003F are identical in both files:
```
03 14 03 6E 00 00 02 24 03 0E 04 40
```

## Menu Entry Format

Every entry in the file (categories AND game titles) uses the same
base structure. Each entry is identified by the marker sequence
`04 1C 03 08` which precedes the null-terminated name string.

### Category Entry (92 bytes)

Categories and game entries share the same wrapper format.
The structure is split into a **prefix** and a **name+pointers** section.

```
Offset  Size  Description
------  ----  -----------
+$00    2     $0428 (entry type: navigable menu item)
+$02    2     Display data pointer high word ($0016 = in $16xxxx range)
+$04    2     Display data pointer low word
+$06    2     $0308 (constant - display command?)

+$08    2     $0422 (sub-entry type: selected state)
+$0A    2     Selection index/variant (0x0002 = unselected cursor)
+$0C    2     $02E4 (X position or dimension)
+$0E    2     $0278 (Y position or dimension)
+$10    4     Ptr to tile/graphic data ($10xxxx range)
+$14    4     Ptr to palette/cursor data ($15xxxx/$13xxxx range)
+$18    4     $00000000 (padding)
+$1C    2     $03B6 (constant - end-of-subentry marker)

+$1E    2     $0422 (sub-entry type: selected state)
+$20    2     Selection index/variant (0x0003 = selected cursor)
+$22    2     $02E4 (X position)
+$24    2     $0278 (Y position)
+$26    4     Ptr to tile/graphic data (same as +$10)
+$28    4     Ptr to palette data (different from +$14)
+$2C    4     $00000000 (padding)
+$30    2     $03B6 (end-of-subentry marker)

+$32    2     $041C (name display command)
+$34    2     $0308 (constant)
+$36    16    Category name (null-terminated, space-padded)
              e.g. "  The Arcade\0\0\0"

+$46    4     Ptr to icon/tile data 1
+$4A    4     Ptr to icon/tile data 2
+$4E    4     Ptr to icon/tile data 3
+$52    4     Ptr to icon/tile data 4
+$56    4     Ptr to expanded content (game list/description area)

+$5A    2     $0000 (entry terminator)
```

Total: ~92 bytes per category entry.

### Game Entry (~152 bytes, appears in pairs)

Game entries follow the same prefix pattern but come in PAIRS
(one for each selection state). Each game has:

**Entry body 1 (unselected state):**
```
+$00    varies  Display parameters block (see category format)
                Same structure: $0422 subentries + $03B6 markers
```

**Entry body 2 (selected state):**
```
+$4A    varies  Second display state
```

**Title block:**
```
+$68    2     $041C (name display command)
+$6A    2     $0308
+$6C    24    Game title (null-terminated, space-padded to 24 chars)
              e.g. "         Alien Storm         \0"
```

**Post-title pointers:**
```
+$84    4     Ptr to tile data 1
+$88    4     Ptr to tile data 2
+$8C    4     Ptr to description text 1
+$90    4     Ptr to description text 2
+$94    4     Ptr to expanded game info / screenshot data
+$98    2     Game flags / game ID
```

Game entries are followed by `04 28` which marks the start of the next entry.

## Game Descriptions

Game descriptions are stored separately from the entries, in the
region pointed to by the post-title pointers. Each description
appears to be stored in up to 4 languages:

1. English
2. French
3. German (only in some entries)
4. Spanish

Each description is a series of short text lines (for the
Genesis's limited text display), null-terminated.

## Pointer Ranges

| Range | Content |
|-------|---------|
| $10xxxx | Tile/graphic data (VDP patterns) |
| $13xxxx | Palette data set 2 (used in 1997V) |
| $15xxxx | Palette data set 1 (used in SCG) |
| $16xxxx | Display list / scroll data |

## Constants

These values appear consistently across both known SCMENU files:

| Value | Meaning |
|-------|---------|
| $0428 | Menu entry header (navigable item) |
| $0422 | Sub-entry (selection state variant) |
| $041C | Name/text display command |
| $0308 | Display parameter constant |
| $03B6 | End of sub-entry marker |
| $02E4 | Standard X dimension |
| $0278 | Standard Y dimension |

## Key Insight: Menu Entry Count

The menu ROM calculates entry count at $600C:
```asm
move.l  $8400.w, d0      ; $FF8400 = end of data in DRAM
subi.l  #$100000, d0      ; subtract SCMENU base
divu.w  #$f6, d0          ; divide by 246
```

This suggests the **game entries** (not categories) follow a 246-byte
($F6) stride in some region of the file. However, the actual entry
sizes in the header area are ~92 bytes. The $F6 division likely applies
to the **expanded game data** region (descriptions + tile data) that
starts deeper in the file, not the menu entry headers.

## For Generating Custom SCMENU.BIN

To create a new SCMENU.BIN:
1. Write the header (copy fixed fields from a known file)
2. Write category entries (92 bytes each, with updated name + pointers)
3. Write game entries (paired, with title + pointers to description data)
4. Write description text blocks (multilingual, pointed to by entries)
5. Write tile/graphic data (can reuse from existing file initially)
6. Update all pointers to reflect new offsets
7. Pad to 615,028 bytes (or adjust $FF8400 to match actual size)
