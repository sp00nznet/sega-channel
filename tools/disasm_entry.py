"""
Focused disassembly of the entry point and key routines.
The full ROM disassembly returned 0 - likely because large chunks are
compressed data/graphics. Let's disassemble just the code sections.
"""

import struct
import sys
from capstone import *

def load_rom(path):
    with open(path, 'rb') as f:
        return f.read()

def disasm_range(rom, start, length, label=""):
    md = Cs(CS_ARCH_M68K, CS_MODE_BIG_ENDIAN)
    md.detail = True
    data = rom[start:start+length]
    instrs = list(md.disasm(data, start))
    if label:
        print(f"\n{'='*60}")
        print(f"  {label} (0x{start:06X} - 0x{start+length:06X})")
        print(f"{'='*60}")
    for insn in instrs:
        print(f"  {insn.address:06X}: {insn.bytes.hex():16s} {insn.mnemonic:10s} {insn.op_str}")
    return instrs

def main():
    rom_path = sys.argv[1] if len(sys.argv) > 1 else "analysis/Sega Channel menu data/Sega Channel Guy/Canada Menu Demo December 1995.BIN"
    rom = load_rom(rom_path)

    # Parse vectors
    vectors = {}
    vector_names = ['sp', 'entry', 'bus_err', 'addr_err', 'illegal', 'divzero',
                    'chk', 'trapv', 'priv_viol', 'trace', 'line_a', 'line_f']
    for i in range(64):
        vectors[i] = struct.unpack('>I', rom[i*4:i*4+4])[0]

    entry = vectors[1]
    vblank = vectors[30]  # int6
    hblank_ext = vectors[25]  # int2

    print(f"Entry: 0x{entry:06X}")
    print(f"VBlank (int6): 0x{vblank:06X}")
    print(f"HBlank/Ext (int2): 0x{hblank_ext:06X}")
    print(f"Trap0: 0x{vectors[32]:06X}")
    print(f"Trap1: 0x{vectors[33]:06X}")
    print(f"Trap2: 0x{vectors[34]:06X}")

    # Entry point - init sequence
    disasm_range(rom, entry, 0x300, "ENTRY POINT / INIT")

    # After init, where does it jump?
    # From the first scan we saw bra.b $912 at 0x8A4
    disasm_range(rom, 0x900, 0x200, "POST-INIT (0x900)")

    # VBlank
    disasm_range(rom, vblank, 0x40, "VBLANK HANDLER")

    # HBlank / ext int
    if hblank_ext and hblank_ext < len(rom):
        disasm_range(rom, hblank_ext, 0x100, "EXT INT / HBLANK HANDLER")

    # Trap handlers - these are often used for system calls in SC
    for trap_num in range(3):
        trap_addr = vectors[32 + trap_num]
        if trap_addr and trap_addr < len(rom):
            disasm_range(rom, trap_addr, 0x80, f"TRAP #{trap_num} HANDLER")

    # The $400000 reference area - this is the adapter DRAM access
    disasm_range(rom, 0x5D80, 0x100, "ADAPTER DRAM CHECK AREA ($400000 refs)")

    # The diagnostic area
    disasm_range(rom, 0x34D0, 0x200, "DIAGNOSTIC ROUTINES")

    # ADAPTER strings area
    disasm_range(rom, 0xAD80, 0x120, "ADAPTER INIT/STATUS AREA")

    # DRAM test
    disasm_range(rom, 0xA780, 0x100, "DRAM TEST AREA")

    # Decompression routine
    disasm_range(rom, 0x40F0, 0x150, "DECOMPRESSION ROUTINE")

    # The area around SCMENU reference
    disasm_range(rom, 0xF080, 0x100, "MENUDATA AREA")

    # Game loading / channel switching area
    # Search for interesting subroutine patterns near the $400000 access
    disasm_range(rom, 0x5C00, 0x300, "ADAPTER COMMUNICATION AREA")

    # Let's also check what's at the boundary between code and data
    # The ROM header says rom_end is 0xFFFFF (1MB) but the file is 2MB
    # Upper 1MB likely contains the menu data (game descriptions, graphics, etc)
    print(f"\n\n=== ROM LAYOUT ANALYSIS ===")
    print(f"Header claims ROM end: 0x{struct.unpack('>I', rom[0x1A4:0x1A8])[0]:06X}")
    print(f"Actual file size: 0x{len(rom):06X}")

    # Check what's at 0x100000 boundary
    print(f"\nData at 0x100000 (1MB boundary):")
    for i in range(0x100000, min(0x100080, len(rom)), 16):
        hex_str = rom[i:i+16].hex()
        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in rom[i:i+16])
        print(f"  {i:06X}: {hex_str}  {ascii_str}")

    # Check data at 0x0F0000 - end of code area?
    print(f"\nData at 0x0F0000:")
    for i in range(0x0F0000, min(0x0F0080, len(rom)), 16):
        hex_str = rom[i:i+16].hex()
        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in rom[i:i+16])
        print(f"  {i:06X}: {hex_str}  {ascii_str}")

    # Where does code stop and data begin? Scan for runs of 00s or FF patterns
    print(f"\nSearching for code/data boundary...")
    for check in range(0x10000, 0x100000, 0x1000):
        chunk = rom[check:check+64]
        # If mostly zeros or repeated patterns, likely data/padding
        zero_count = chunk.count(0)
        if zero_count > 48:
            print(f"  0x{check:06X}: Mostly zeros ({zero_count}/64)")
        elif len(set(chunk)) < 8:
            print(f"  0x{check:06X}: Low entropy (only {len(set(chunk))} unique bytes)")

if __name__ == '__main__':
    main()
