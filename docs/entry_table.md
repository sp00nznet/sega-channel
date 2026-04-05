# SCMENU Entry Table - Canada Menu Demo December 1995

## Key Finding

ALL game/category entries are in the SCMENU data area ($100000+), 
not in the ROM code. Custom menus are possible by modifying this data.

## Entry Table Location

The entry table starts at file offset $10050C (runtime $10050C).
Each entry begins with the `$0428` header marker.

## Structure

| Range | Count | Type | Typical Size |
|-------|-------|------|-------------|
| Entries 0-9 | 10 | Categories | 100 bytes |
| Entries 10-59 | 50 | Games | 150-412 bytes (~160 avg) |
| Entries 60+ | ~100 | Expanded content (descriptions) | 54 + ~2400 bytes (pairs) |

## Entry Addresses

### Categories
| # | Address | Size | Title |
|---|---------|------|-------|
| 0 | $10050C | 100 | Test Drives |
| 1 | $100570 | 100 | The Arcade |
| 2 | $1005D4 | 98 | Puzzlers |
| 3 | $100636 | 100 | Family Room |
| 4 | $10069A | 100 | Sports Arena |
| 5 | $1006FE | 100 | The Stadium |
| 6 | $100762 | 102 | Wings 'N Wheels |
| 7 | $1007C8 | 100 | The Dungeon |
| 8 | $10082C | 100 | News Link |
| 9 | $100890 | 320 | Game Guide |

### Games
| # | Address | Size | Title |
|---|---------|------|-------|
| 10 | $1009D0 | 154 | Earthworm Jim 2 |
| 11 | $100A6A | 150 | Garfield |
| 12 | $100B00 | 154 | Mutant Chronicles |
| 13 | $100B9A | 150 | Vectorman |
| 14 | $100C30 | 412 | VR Troopers |
| 15 | $100DCC | 160 | Alex Kidd |
| 16 | $100E6C | 160 | Art of Fighting |
| 17 | $100F0C | 160 | Blades of Vengeance |
| 18 | $100FAC | 160 | Bonanza Bros. |
| 19 | $10104C | 160 | Bubsy |
| 20 | $1010EC | 160 | Castlevania |
| 21 | $10118C | 160 | Comix Zone |
| 22 | $10122C | 160 | Desert Strike |
| 23 | $1012CC | 160 | Dynamite Headdy |
| 24 | $10136C | 160 | Golden Axe II |
| 25 | $10140C | 160 | Jewel Master |
| 26 | $1014AC | 160 | seaQuest DSV |
| 27 | $10154C | 160 | Skeleton Krew |
| 28 | $1015EC | 160 | Sonic The Hedgehog |
| 29 | $10168C | 388 | Space Invaders '91 |
| 30 | $101810 | 160 | David Robinson's Court |
| 31 | $1018B0 | 160 | FIFA Soccer '95 |
| 32 | $101950 | 160 | Int'l Rugby (SC Exclu.) |
| 33 | $1019F0 | 160 | Mutant League Hockey |
| 34 | $101A90 | 160 | NHL All-Star Hockey '95 |
| 35 | $101B30 | 160 | Pele! |
| 36 | $101BD0 | 340 | World Series Baseball |
| 37 | $101D24 | 154 | Phantasy Star IV |
| 38 | $101DBE | 154 | Shining Force II |
| 39 | $101E58 | 372 | TechnoClash |
| 40 | $101FCC | 156 | Mig-29 Fighter Pilot |
| 41 | $102068 | 148 | Outrun |
| 42 | $1020FC | 152 | Road Rash II |
| 43 | $102194 | 150 | Skitchin' |
| 44 | $10222A | 342 | Super Monaco GP |
| 45 | $102380 | 152 | Dr. Robotnik |
| 46 | $102418 | 158 | Jeopardy! Deluxe Edition |
| 47 | $1024B6 | 150 | Monopoly |
| 48 | $10254C | 152 | Sonic Spinball |
| 49 | $1025E4 | 374 | Theme Park |
| 50 | $10275A | 160 | Animaniacs |
| 51 | $1027FA | 160 | Art Alive |
| 52 | $10289A | 160 | Berenstain Bears |
| 53 | $10293A | 160 | Crystal's Pony Tale |
| 54 | $1029DA | 160 | Ecco Jr. |
| 55 | $102A7A | 344 | Rolo to the Rescue |
| 56 | $102BD2 | 156 | Bass Masters Classic |
| 57 | $102C6E | 158 | Best of the Best Karate |
| 58 | $102D0C | 154 | Championship Pool |
| 59 | $102DA6 | 2648 | PGA Tour Golf III |

## Entry Format

Each `$0428` entry has:
```
$0428           - Entry header
$0016:XXXX      - Display data pointer
$0308           - Display parameter
$0422 variant1  - Unselected cursor state (coords, tile/palette ptrs)
$03B6           - End sub-entry
$0422 variant2  - Selected cursor state
$03B6           - End sub-entry
$041C $0308     - Name display command
Title text      - Null-terminated, space-padded (16 or 24 chars)
$0010:XXXX x5   - Post-name pointers (tiles, palette, expanded content)
$0000           - Entry terminator
```

## Implications

### ROM Patcher (Track 1)
Modify entries 10-59 in any SC menu ROM to insert custom game titles.
The title text is at a known offset within each entry (after `$041C $0308`).
Entry sizes vary — for simple title swaps, keep the same entry boundaries.

### Custom ROM (Track 2)  
Generate the entire entry table from scratch using the `$0428` format.
Build category entries (0-9) and game entries (10-59) with proper
display parameters and pointers. The display parameter values can
be copied from a template entry.
