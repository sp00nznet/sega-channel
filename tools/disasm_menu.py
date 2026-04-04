"""
Sega Channel Menu ROM Disassembler & Hardware Analyzer

Analyzes the menu ROM to understand:
- How it communicates with the Sega Channel adapter hardware
- Memory-mapped I/O addresses used
- The protocol for requesting/receiving game data
- Data format structures
"""

import struct
import sys
from capstone import *
from collections import defaultdict

def load_rom(path):
    with open(path, 'rb') as f:
        return f.read()

def parse_genesis_header(rom):
    """Parse the standard Genesis/Mega Drive ROM header at 0x100"""
    if len(rom) < 0x200:
        print("ROM too small for header")
        return None

    header = {}
    header['console'] = rom[0x100:0x110].decode('ascii', errors='replace').strip('\x00')
    header['copyright'] = rom[0x110:0x120].decode('ascii', errors='replace').strip('\x00')
    header['title_domestic'] = rom[0x120:0x150].decode('ascii', errors='replace').strip('\x00')
    header['title_overseas'] = rom[0x150:0x180].decode('ascii', errors='replace').strip('\x00')
    header['serial'] = rom[0x180:0x18E].decode('ascii', errors='replace').strip('\x00')
    header['checksum'] = struct.unpack('>H', rom[0x18E:0x190])[0]
    header['io_support'] = rom[0x190:0x1A0].decode('ascii', errors='replace').strip('\x00')
    header['rom_start'] = struct.unpack('>I', rom[0x1A0:0x1A4])[0]
    header['rom_end'] = struct.unpack('>I', rom[0x1A4:0x1A8])[0]
    header['ram_start'] = struct.unpack('>I', rom[0x1A8:0x1AC])[0]
    header['ram_end'] = struct.unpack('>I', rom[0x1AC:0x1B0])[0]
    header['sram_info'] = rom[0x1B0:0x1B4].hex()
    header['sram_start'] = struct.unpack('>I', rom[0x1B4:0x1B8])[0]
    header['sram_end'] = struct.unpack('>I', rom[0x1B8:0x1BC])[0]
    header['modem'] = rom[0x1BC:0x1C8].decode('ascii', errors='replace').strip('\x00')
    header['memo'] = rom[0x1C8:0x1F0].decode('ascii', errors='replace').strip('\x00')
    header['region'] = rom[0x1F0:0x200].decode('ascii', errors='replace').strip('\x00')
    return header

def parse_vectors(rom):
    """Parse the 68000 exception vector table at offset 0"""
    vectors = {}
    vector_names = [
        'initial_sp', 'entry_point',
        'bus_error', 'address_error', 'illegal_instr', 'div_zero',
        'chk_instr', 'trapv', 'privilege_violation', 'trace',
        'line_a', 'line_f',
        'reserved_12', 'reserved_13', 'reserved_14', 'reserved_15',
        'reserved_16', 'reserved_17', 'reserved_18', 'reserved_19',
        'reserved_20', 'reserved_21', 'reserved_22', 'reserved_23',
        'spurious_int',
        'int1_ext', 'int2_ext_hblank', 'int3', 'int4_hblank',
        'int5', 'int6_vblank', 'int7_nmi',
        'trap0', 'trap1', 'trap2', 'trap3', 'trap4', 'trap5',
        'trap6', 'trap7', 'trap8', 'trap9', 'trap10', 'trap11',
        'trap12', 'trap13', 'trap14', 'trap15',
    ]
    for i, name in enumerate(vector_names):
        offset = i * 4
        if offset + 4 <= len(rom):
            vectors[name] = struct.unpack('>I', rom[offset:offset+4])[0]
    return vectors

# Address ranges of interest for Sega Channel adapter
# The adapter cartridge mapped into $400000-$7FFFFF typically
# Also uses some I/O at $A130xx for bank switching
ADAPTER_RANGES = [
    (0x400000, 0x7FFFFF, "Sega Channel Adapter (cartridge space)"),
    (0xA13000, 0xA130FF, "Cartridge I/O / bank switch registers"),
    (0xA14000, 0xA140FF, "TMSS register area"),
    (0xA10000, 0xA100FF, "I/O registers"),
]

# Known Genesis VDP/hardware addresses
HW_RANGES = [
    (0xC00000, 0xC00003, "VDP Data Port"),
    (0xC00004, 0xC00007, "VDP Control Port"),
    (0xC00008, 0xC0000B, "VDP HV Counter"),
    (0xC00011, 0xC00011, "PSG"),
    (0xA00000, 0xA0FFFF, "Z80 RAM"),
    (0xA10000, 0xA1001F, "I/O Area"),
    (0xA11100, 0xA11101, "Z80 Bus Request"),
    (0xA11200, 0xA11201, "Z80 Reset"),
    (0xFF0000, 0xFFFFFF, "68K RAM"),
]

def classify_address(addr):
    """Classify a memory address by what hardware region it belongs to"""
    for start, end, name in ADAPTER_RANGES:
        if start <= addr <= end:
            return f"*** ADAPTER: {name} ***"
    for start, end, name in HW_RANGES:
        if start <= addr <= end:
            return name
    if addr < 0x400000:
        return "ROM"
    return "Unknown"

def disassemble_rom(rom, start_offset=0, length=None, base_addr=0):
    """Disassemble 68000 code from ROM data"""
    md = Cs(CS_ARCH_M68K, CS_MODE_BIG_ENDIAN)
    md.detail = True

    if length is None:
        length = len(rom) - start_offset

    data = rom[start_offset:start_offset + length]
    instructions = list(md.disasm(data, base_addr + start_offset))
    return instructions

def find_hardware_accesses(rom, start=None, end=None):
    """
    Scan disassembly for any accesses to interesting address ranges.
    Focuses on finding Sega Channel adapter I/O.
    """
    md = Cs(CS_ARCH_M68K, CS_MODE_BIG_ENDIAN)
    md.detail = True

    if start is None:
        start = 0
    if end is None:
        end = len(rom)

    data = rom[start:end]

    hw_accesses = defaultdict(list)
    adapter_accesses = []

    for insn in md.disasm(data, start):
        op_str = insn.op_str
        mnemonic = insn.mnemonic

        # Look for absolute addresses in operands
        # Check for immediate values and absolute addresses
        for op in insn.operands:
            addr = None
            if op.type == 1:  # IMM
                addr = op.imm & 0xFFFFFFFF
            elif op.type == 4:  # MEM (absolute)
                if hasattr(op.mem, 'disp'):
                    addr = op.mem.disp & 0xFFFFFFFF

            if addr is not None and addr >= 0x400000:
                classification = classify_address(addr)
                entry = {
                    'pc': insn.address,
                    'instruction': f"{mnemonic} {op_str}",
                    'target_addr': addr,
                    'classification': classification,
                    'bytes': rom[insn.address:insn.address+insn.size].hex(),
                }
                hw_accesses[classification].append(entry)
                if "ADAPTER" in classification:
                    adapter_accesses.append(entry)

    return hw_accesses, adapter_accesses

def find_strings(rom, min_length=4):
    """Find ASCII strings in ROM data"""
    strings = []
    current = b''
    start = 0
    for i, byte in enumerate(rom):
        if 0x20 <= byte < 0x7F:
            if not current:
                start = i
            current += bytes([byte])
        else:
            if len(current) >= min_length:
                strings.append((start, current.decode('ascii')))
            current = b''
    return strings

def analyze_menu_rom(rom_path):
    """Full analysis of a Sega Channel menu ROM"""
    rom = load_rom(rom_path)
    print(f"=== Sega Channel Menu ROM Analysis ===")
    print(f"File: {rom_path}")
    print(f"Size: {len(rom)} bytes ({len(rom)/1024:.1f} KB)")
    print()

    # Parse header
    header = parse_genesis_header(rom)
    if header:
        print("--- Genesis Header ---")
        for k, v in header.items():
            if isinstance(v, int):
                print(f"  {k}: 0x{v:08X} ({v})")
            else:
                print(f"  {k}: {v}")
        print()

    # Parse vectors
    vectors = parse_vectors(rom)
    print("--- Exception Vectors ---")
    for name, addr in vectors.items():
        if addr != 0 and addr != vectors.get('bus_error', 0) or name in ('initial_sp', 'entry_point'):
            marker = ""
            if name in ('entry_point', 'int6_vblank', 'int4_hblank', 'int2_ext_hblank'):
                marker = " <-- IMPORTANT"
            print(f"  {name}: 0x{addr:08X}{marker}")
    print()

    # Disassemble entry point
    entry = vectors.get('entry_point', 0x200)
    print(f"--- Entry Point Disassembly (0x{entry:06X}) ---")
    instrs = disassemble_rom(rom, start_offset=entry, length=0x200, base_addr=0)
    for insn in instrs[:80]:
        print(f"  {insn.address:06X}: {insn.mnemonic:10s} {insn.op_str}")
    print("  ...")
    print()

    # Disassemble VBlank handler
    vblank = vectors.get('int6_vblank', 0)
    if vblank and vblank < len(rom):
        print(f"--- VBlank Handler (0x{vblank:06X}) ---")
        instrs = disassemble_rom(rom, start_offset=vblank, length=0x200, base_addr=0)
        for insn in instrs[:60]:
            print(f"  {insn.address:06X}: {insn.mnemonic:10s} {insn.op_str}")
        print("  ...")
        print()

    # Scan for hardware accesses - this is the key part
    print("--- Scanning for Hardware Accesses ---")
    print("(Looking for reads/writes to adapter addresses $400000-$7FFFFF)")
    print()

    hw_accesses, adapter_accesses = find_hardware_accesses(rom)

    if adapter_accesses:
        print(f"*** FOUND {len(adapter_accesses)} ADAPTER ACCESSES ***")
        print()
        seen_addrs = set()
        for acc in adapter_accesses:
            addr = acc['target_addr']
            if addr not in seen_addrs:
                seen_addrs.add(addr)
                print(f"  Adapter addr 0x{addr:08X} accessed at PC=0x{acc['pc']:06X}")
                print(f"    Instruction: {acc['instruction']}")
                print(f"    Classification: {acc['classification']}")
                print()

        print(f"\nUnique adapter addresses accessed: {len(seen_addrs)}")
        for addr in sorted(seen_addrs):
            count = sum(1 for a in adapter_accesses if a['target_addr'] == addr)
            print(f"  0x{addr:08X} - {count} access(es)")
    else:
        print("  No direct adapter accesses found via absolute addressing.")
        print("  (Adapter may be accessed via register-indirect addressing)")
        print("  Will need deeper analysis...")

    print()

    # Also report other hardware accesses
    for classification, accesses in sorted(hw_accesses.items()):
        if "ADAPTER" not in classification:
            unique = set(a['target_addr'] for a in accesses)
            print(f"  {classification}: {len(accesses)} accesses ({len(unique)} unique addrs)")

    print()

    # Find strings - useful for understanding menu structure
    print("--- Notable Strings ---")
    strings = find_strings(rom, min_length=6)
    for offset, s in strings:
        # Filter to interesting ones
        if any(kw in s.lower() for kw in ['channel', 'sega', 'game', 'menu', 'download',
                                            'load', 'select', 'play', 'error', 'connect',
                                            'adapter', 'transfer', 'arcade', 'sport',
                                            'family', 'strategy', 'room', 'test', 'demo',
                                            'press', 'start', 'button', 'welcome',
                                            'version', 'copyright']):
            print(f"  0x{offset:06X}: \"{s}\"")

    print()
    print("=== Analysis Complete ===")
    return hw_accesses, adapter_accesses

if __name__ == '__main__':
    if len(sys.argv) < 2:
        rom_path = "/tmp/sega_channel_analysis/Sega Channel menu data/Sega Channel Guy/Canada Menu Demo December 1995.BIN"
    else:
        rom_path = sys.argv[1]

    analyze_menu_rom(rom_path)
