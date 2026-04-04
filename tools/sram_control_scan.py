"""
Deep analysis of the SRAM control protocol at $200000.

When $A130F0 = 1, the address range $200000-$203FFF maps to adapter
control/SRAM space. We need to find every code path that:
1. Sets $A130F0 = 1 (enters control mode)
2. Reads/writes to the $200000 range
3. Clears $A130F0 (exits control mode)

This will reveal the full command protocol between the menu ROM
and the adapter hardware.
"""

import struct
import sys
from capstone import *
from collections import defaultdict

def load_rom(path):
    with open(path, 'rb') as f:
        return f.read()

def disasm_range(rom, start, length):
    md = Cs(CS_ARCH_M68K, CS_MODE_BIG_ENDIAN)
    md.detail = True
    data = rom[start:start+length]
    return list(md.disasm(data, start))

def disasm_function(rom, start, max_length=0x400):
    """Disassemble a function from start, stopping at RTS or max_length"""
    md = Cs(CS_ARCH_M68K, CS_MODE_BIG_ENDIAN)
    md.detail = True
    data = rom[start:start+max_length]
    instrs = []
    for insn in md.disasm(data, start):
        instrs.append(insn)
        if insn.mnemonic == 'rts' or insn.mnemonic == 'rte':
            break
    return instrs

def find_all_a130f0_refs(rom):
    """Find every reference to $A130F0 in the ROM"""
    target = struct.pack('>I', 0x00A130F0)
    refs = []
    idx = 0
    while True:
        idx = rom.find(target, idx)
        if idx < 0:
            break
        refs.append(idx)
        idx += 1
    return refs

def find_all_200000_refs(rom):
    """Find every reference to addresses in the $200000 range"""
    results = []
    # Check for $200000, $200001, and nearby
    for base in range(0x200000, 0x204000, 2):
        target = struct.pack('>I', base)
        idx = 0
        while True:
            idx = rom.find(target, idx)
            if idx < 0:
                break
            results.append((idx, base))
            idx += 1
    return results

def find_function_start(rom, addr):
    """Try to find the start of a function containing the given address.
    Walk backwards looking for RTS, RTE, or alignment padding."""
    md = Cs(CS_ARCH_M68K, CS_MODE_BIG_ENDIAN)
    md.detail = True

    # Simple heuristic: scan backwards for common function boundaries
    for scan_back in range(2, 0x200, 2):
        check = addr - scan_back
        if check < 0:
            return 0
        # Check if previous instruction is RTS
        word = struct.unpack('>H', rom[check:check+2])[0]
        if word == 0x4E75:  # RTS
            return check + 2
        if word == 0x4E73:  # RTE
            return check + 2
    return max(0, addr - 0x40)

def main():
    rom_path = sys.argv[1] if len(sys.argv) > 1 else "analysis/Sega Channel menu data/Sega Channel Guy/Canada Menu Demo December 1995.BIN"
    rom = load_rom(rom_path)
    md = Cs(CS_ARCH_M68K, CS_MODE_BIG_ENDIAN)
    md.detail = True

    print("=" * 70)
    print("  SEGA CHANNEL ADAPTER SRAM CONTROL PROTOCOL ANALYSIS")
    print("=" * 70)

    # 1. Find all $A130F0 references
    print("\n\n### ALL REFERENCES TO $A130F0 (Bank Switch Register) ###\n")
    a130_refs = find_all_a130f0_refs(rom)
    print(f"Found {len(a130_refs)} raw references to $A130F0")

    a130_contexts = []
    for ref in a130_refs:
        # Disassemble the instruction at this reference
        # The reference might be in the middle of an instruction
        # Try a few offsets back
        for offset in range(0, 8, 2):
            start = ref - offset
            if start < 0:
                continue
            instrs = list(md.disasm(rom[start:start+12], start))
            for insn in instrs:
                if insn.address <= ref < insn.address + insn.size:
                    if '$a130f0' in insn.op_str.lower() or '0xa130f0' in insn.op_str.lower():
                        a130_contexts.append(insn)
                        break
            else:
                continue
            break

    for insn in a130_contexts:
        print(f"  0x{insn.address:06X}: {insn.mnemonic:10s} {insn.op_str}")

    # 2. Find all $200000-range references
    print("\n\n### ALL REFERENCES TO $200000 RANGE (SRAM/Control Space) ###\n")
    sram_refs = find_all_200000_refs(rom)
    print(f"Found {len(sram_refs)} raw references to $200000 range")

    sram_addrs = set()
    sram_contexts = []
    for ref, target_addr in sram_refs:
        for offset in range(0, 8, 2):
            start = ref - offset
            if start < 0:
                continue
            instrs = list(md.disasm(rom[start:start+12], start))
            for insn in instrs:
                if insn.address <= ref < insn.address + insn.size:
                    sram_contexts.append((insn, target_addr))
                    sram_addrs.add(target_addr)
                    break
            else:
                continue
            break

    for insn, target in sram_contexts:
        print(f"  0x{insn.address:06X}: {insn.mnemonic:10s} {insn.op_str}  [target: 0x{target:06X}]")

    print(f"\nUnique SRAM addresses accessed: {sorted(f'0x{a:06X}' for a in sram_addrs)}")

    # 3. For each $A130F0 access, disassemble the full function context
    print("\n\n### FULL FUNCTION CONTEXT FOR EACH $A130F0 ACCESS ###\n")

    seen_functions = set()
    for insn in a130_contexts:
        func_start = find_function_start(rom, insn.address)
        if func_start in seen_functions:
            continue
        seen_functions.add(func_start)

        print(f"\n{'─'*60}")
        print(f"  FUNCTION at 0x{func_start:06X} (contains $A130F0 access at 0x{insn.address:06X})")
        print(f"{'─'*60}")

        # Disassemble until RTS, but go a bit further to catch multi-exit functions
        func_instrs = []
        rts_count = 0
        for fi in md.disasm(rom[func_start:func_start+0x200], func_start):
            func_instrs.append(fi)
            if fi.mnemonic in ('rts', 'rte'):
                rts_count += 1
                if rts_count >= 3:  # Stop after 3rd RTS (handles subfunctions)
                    break

        for fi in func_instrs:
            marker = ""
            if '$a130f0' in fi.op_str.lower():
                marker = "  ◄── BANK SWITCH"
            elif '$20000' in fi.op_str.lower():
                marker = "  ◄── SRAM ACCESS"
            elif fi.mnemonic in ('bsr', 'jsr'):
                marker = f"  → call"
            print(f"  {fi.address:06X}: {fi.bytes.hex():16s} {fi.mnemonic:10s} {fi.op_str}{marker}")

    # 4. Now scan for ALL code that accesses $200000-$2FFFFF while $A130F0 could be set
    # Look for patterns: set $A130F0, then access $200000 range, then clear $A130F0
    print("\n\n### SRAM CONTROL SEQUENCES (Set → Access → Clear) ###\n")

    # Find all set/clear pairs
    a130_set_addrs = [insn.address for insn in a130_contexts
                       if '#$1' in insn.op_str or '#1' in insn.op_str or '#$0001' in insn.op_str]
    a130_clr_addrs = [insn.address for insn in a130_contexts
                       if 'clr' in insn.mnemonic or '#$0' in insn.op_str or '#0' in insn.op_str]

    print(f"$A130F0 SET locations: {[f'0x{a:06X}' for a in a130_set_addrs]}")
    print(f"$A130F0 CLR locations: {[f'0x{a:06X}' for a in a130_clr_addrs]}")

    # For each SET, find the nearest CLR and show everything between
    for set_addr in a130_set_addrs:
        nearest_clr = None
        for clr_addr in a130_clr_addrs:
            if clr_addr > set_addr:
                if nearest_clr is None or clr_addr < nearest_clr:
                    nearest_clr = clr_addr

        if nearest_clr:
            print(f"\n  SRAM Session: 0x{set_addr:06X} → 0x{nearest_clr:06X}")
            print(f"  Duration: {nearest_clr - set_addr} bytes of code")

            # Disassemble the entire session
            session_len = nearest_clr - set_addr + 16
            for insn in md.disasm(rom[set_addr:set_addr+session_len], set_addr):
                marker = ""
                if '$a130f0' in insn.op_str.lower():
                    marker = "  ◄── BANK SWITCH"
                elif '0x20' in insn.op_str or '$20000' in insn.op_str.lower():
                    marker = "  ◄── SRAM ACCESS"
                print(f"    {insn.address:06X}: {insn.mnemonic:10s} {insn.op_str}{marker}")

    # 5. Scan for other adapter-related I/O patterns
    print("\n\n### OTHER ADAPTER I/O PATTERNS ###\n")

    # Check for accesses to $A130F1-$A130FF (other bank switch regs)
    for reg in range(0xA130F1, 0xA13100):
        target = struct.pack('>I', reg)
        idx = rom.find(target)
        if idx >= 0:
            print(f"  Reference to 0x{reg:08X} at offset 0x{idx:06X}")

    # Check $A130E0-$A130EF range too
    for reg in range(0xA130E0, 0xA130F0):
        target = struct.pack('>I', reg)
        idx = rom.find(target)
        if idx >= 0:
            print(f"  Reference to 0x{reg:08X} at offset 0x{idx:06X}")

    # 6. Scan for reads FROM the $200000 range (not just writes)
    print("\n\n### SRAM READ vs WRITE ANALYSIS ###\n")

    for insn, target in sram_contexts:
        # Determine if this is a read or write
        op_str = insn.op_str
        mnemonic = insn.mnemonic

        if mnemonic.startswith('lea'):
            direction = "LOAD_ADDR"
        elif mnemonic.startswith('move') or mnemonic.startswith('clr'):
            # Check if destination contains the SRAM address
            parts = op_str.split(',')
            if len(parts) == 2:
                dest = parts[1].strip()
                if '$20000' in parts[0] or '0x20000' in parts[0]:
                    direction = "READ"
                else:
                    direction = "WRITE"
            else:
                direction = "UNKNOWN"
        elif mnemonic.startswith('tst') or mnemonic.startswith('cmp') or mnemonic.startswith('btst'):
            direction = "READ/TEST"
        else:
            direction = mnemonic.upper()

        print(f"  0x{insn.address:06X}: [{direction:10s}] {mnemonic} {op_str}  → 0x{target:06X}")

    # 7. Search for subroutine calls that handle adapter communication
    print("\n\n### ADAPTER COMMUNICATION SUBROUTINES ###\n")

    # The functions at $56E2, $569E, $5706, $56C0 are called from the adapter area
    # Let's disassemble them
    comm_subs = [0x569E, 0x56C0, 0x56E2, 0x5706]
    for sub_addr in comm_subs:
        print(f"\n  Subroutine at 0x{sub_addr:06X}:")
        instrs = disasm_function(rom, sub_addr, 0x100)
        for insn in instrs:
            marker = ""
            if '$a130f0' in insn.op_str.lower():
                marker = "  ◄── BANK SWITCH"
            elif '0x20' in insn.op_str and '0000' in insn.op_str:
                marker = "  ◄── SRAM ACCESS"
            print(f"    {insn.address:06X}: {insn.bytes.hex():16s} {insn.mnemonic:10s} {insn.op_str}{marker}")

    # 8. Look for the game selection / download trigger
    print("\n\n### GAME SELECTION / DOWNLOAD TRIGGER SEARCH ###\n")

    # Search for "UCMP" magic ($55434D50) which appeared in the game loading code
    ucmp_bytes = struct.pack('>I', 0x55434D50)
    idx = 0
    while True:
        idx = rom.find(ucmp_bytes, idx)
        if idx < 0:
            break
        print(f"  'UCMP' magic found at 0x{idx:06X}")
        # Show context
        ctx_start = max(0, idx - 16)
        for insn in md.disasm(rom[ctx_start:idx+32], ctx_start):
            marker = " <-- UCMP" if insn.address <= idx < insn.address + insn.size else ""
            print(f"    {insn.address:06X}: {insn.mnemonic:10s} {insn.op_str}{marker}")
        idx += 1

    # Check for the comparison against UCMP in code
    # cmpi.l #$55434D50 = 0C9055434D50
    cmp_ucmp = bytes.fromhex('0c9055434d50')
    idx = 0
    while True:
        idx = rom.find(cmp_ucmp, idx)
        if idx < 0:
            break
        print(f"\n  UCMP comparison at 0x{idx:06X}:")
        ctx_start = max(0, idx - 32)
        for insn in md.disasm(rom[ctx_start:idx+64], ctx_start):
            marker = " <-- UCMP CHECK" if insn.address == idx else ""
            print(f"    {insn.address:06X}: {insn.mnemonic:10s} {insn.op_str}{marker}")
        idx += 1

    # 9. Look for the code path from game selection to adapter load
    # The $100000 reference suggests data overlay
    print("\n\n### $100000 REFERENCES (ROM overlay / game data target) ###\n")
    target = struct.pack('>I', 0x00100000)
    idx = 0
    while True:
        idx = rom.find(target, idx)
        if idx < 0:
            break
        for offset in range(0, 8, 2):
            start = idx - offset
            if start < 0:
                continue
            instrs = list(md.disasm(rom[start:start+12], start))
            for insn in instrs:
                if insn.address <= idx < insn.address + insn.size:
                    print(f"  0x{insn.address:06X}: {insn.mnemonic:10s} {insn.op_str}")
                    break
            else:
                continue
            break
        idx += 1

    print("\n" + "=" * 70)
    print("  ANALYSIS COMPLETE")
    print("=" * 70)

if __name__ == '__main__':
    main()
