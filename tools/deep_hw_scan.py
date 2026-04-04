"""
Deep scan for Sega Channel adapter hardware interface.

The adapter maps into the Genesis address space. Known info:
- The adapter had 4MB DRAM mapped at $400000-$7FFFFF
- Control registers likely at $A130xx (standard cart I/O area)
- Game data was loaded into DRAM, menu ROM read from there

This script looks for:
1. Register loads with adapter-range base addresses
2. Reads/writes to $A130xx bank switch registers
3. Any patterns that look like adapter communication protocols
4. Memory copy routines that move data from cart space to RAM
"""

import struct
import sys
from capstone import *
from collections import defaultdict

def load_rom(path):
    with open(path, 'rb') as f:
        return f.read()

def deep_scan(rom_path):
    rom = load_rom(rom_path)
    md = Cs(CS_ARCH_M68K, CS_MODE_BIG_ENDIAN)
    md.detail = True

    print(f"=== Deep Hardware Scan: {rom_path} ===")
    print(f"ROM size: {len(rom)} bytes")
    print()

    # Strategy: look for move/lea instructions that load addresses >= $400000 into registers
    # Then track those registers for subsequent memory accesses

    interesting = []
    register_loads = []  # Instructions that load high addresses into address registers
    bank_switch = []     # Accesses to $A130xx
    adapter_region = []  # Any reference to $400000-$7FFFFF range

    all_instructions = list(md.disasm(rom, 0))
    print(f"Total instructions disassembled: {len(all_instructions)}")
    print()

    for i, insn in enumerate(all_instructions):
        op_str = insn.op_str
        mnemonic = insn.mnemonic

        # Check raw bytes for embedded addresses in the $400000-$7FFFFF range
        # Move immediate to address register: movea.l #$xxxxxxxx, An
        # LEA $xxxxxxxx, An

        # Look for any operand referencing our ranges of interest
        for op in insn.operands:
            val = None
            if op.type == 1:  # IMM
                val = op.imm & 0xFFFFFFFF
            elif op.type == 4:  # MEM
                if hasattr(op.mem, 'disp'):
                    val = op.mem.disp & 0xFFFFFFFF

            if val is None:
                continue

            # Adapter DRAM range
            if 0x400000 <= val <= 0x7FFFFF:
                adapter_region.append((insn.address, f"{mnemonic} {op_str}", val))

            # Bank switch / cart control registers
            if 0xA13000 <= val <= 0xA130FF:
                bank_switch.append((insn.address, f"{mnemonic} {op_str}", val))

            # Also catch high address loads into address registers
            # These could be base pointers for adapter access
            if val >= 0x400000 and val < 0x800000:
                if 'a' in op_str.lower() and ('move' in mnemonic or 'lea' in mnemonic):
                    register_loads.append((insn.address, f"{mnemonic} {op_str}", val))

    # Report findings
    print("=== ADAPTER DRAM REGION ($400000-$7FFFFF) REFERENCES ===")
    if adapter_region:
        for pc, instr, addr in adapter_region:
            print(f"  0x{pc:06X}: {instr}  [target: 0x{addr:06X}]")
    else:
        print("  None found via immediate/absolute addressing")
    print()

    print("=== BANK SWITCH / CART CONTROL ($A130xx) REFERENCES ===")
    if bank_switch:
        for pc, instr, addr in bank_switch:
            print(f"  0x{pc:06X}: {instr}  [reg: 0x{addr:06X}]")
    else:
        print("  None found")
    print()

    print("=== ADDRESS REGISTER LOADS WITH HIGH ADDRESSES ===")
    if register_loads:
        for pc, instr, addr in register_loads:
            print(f"  0x{pc:06X}: {instr}  [addr: 0x{addr:06X}]")
    else:
        print("  None found")
    print()

    # Now let's look at the code around the "ADAPTER" related strings
    # Find offset of key strings
    print("=== CODE NEAR ADAPTER-RELATED STRINGS ===")
    adapter_strings = [
        b"ADAPTER NOT INITIALIZED",
        b"ADAPTER INITIALIZED",
        b"ADAPTER ADDRESS",
        b"TESTING DRAM",
        b"MEMORY TEST",
        b"GAME_ID",
        b"GAME_TIMEOUT",
        b"FIXIT_STARTADDR",
        b"ERROR_COUNTER",
        b"Current Logical Channel",
        b"Current Channel",
        b"MENUDATA",
        b"Decompressing",
        b"PAY-PER-PLAY",
    ]

    for s in adapter_strings:
        idx = rom.find(s)
        if idx >= 0:
            print(f"\n  String '{s.decode()}' at 0x{idx:06X}")
            # Find references to this address in the code
            addr_bytes = struct.pack('>I', idx)
            # Search for 32-bit references
            ref_idx = 0
            refs_found = 0
            while True:
                ref_idx = rom.find(addr_bytes, ref_idx)
                if ref_idx < 0:
                    break
                if ref_idx != idx:  # Don't match the string itself
                    print(f"    Referenced from 0x{ref_idx:06X}")
                    refs_found += 1
                    # Disassemble around the reference
                    scan_start = max(0, ref_idx - 16)
                    scan_data = rom[scan_start:ref_idx + 32]
                    for disasm_insn in md.disasm(scan_data, scan_start):
                        if abs(disasm_insn.address - ref_idx) <= 16:
                            marker = " <---" if disasm_insn.address <= ref_idx < disasm_insn.address + disasm_insn.size else ""
                            print(f"      0x{disasm_insn.address:06X}: {disasm_insn.mnemonic:10s} {disasm_insn.op_str}{marker}")
                ref_idx += 1
            if refs_found == 0:
                # Try 16-bit reference (PC-relative or short)
                addr_16 = struct.pack('>H', idx & 0xFFFF)
                print(f"    (No 32-bit refs found, string may be accessed PC-relative)")

    # Scan for specific 68k patterns related to adapter communication
    print("\n\n=== SCANNING FOR ADAPTER COMMUNICATION PATTERNS ===")

    # Pattern: Writing to $A130F1 (SRAM/bank control) - common for Sega Channel
    # The adapter used bank switching via $A130F1-$A130FF
    for i, insn in enumerate(all_instructions):
        op_str = insn.op_str
        # Look for writes to the $A130Fx range specifically
        if '$a130f' in op_str.lower() or '$a130e' in op_str.lower():
            # Get context
            start_i = max(0, i - 3)
            end_i = min(len(all_instructions), i + 4)
            print(f"\n  Bank control access at 0x{insn.address:06X}:")
            for j in range(start_i, end_i):
                ctx = all_instructions[j]
                marker = " <---" if j == i else ""
                print(f"    0x{ctx.address:06X}: {ctx.mnemonic:10s} {ctx.op_str}{marker}")

    # Also search for raw byte patterns that reference $A130xx
    print("\n\n=== RAW BYTE SCAN FOR $A130xx REFERENCES ===")
    for target in [0xA130F1, 0xA130F3, 0xA130F5, 0xA130F7, 0xA130F9, 0xA130FB, 0xA130FD, 0xA130FF,
                   0xA13001, 0xA13003, 0xA13005, 0xA13007, 0xA13009, 0xA1300B, 0xA1300D, 0xA1300F]:
        target_bytes = struct.pack('>I', target)
        idx = 0
        while True:
            idx = rom.find(target_bytes, idx)
            if idx < 0:
                break
            # Disassemble this instruction
            for disasm_insn in md.disasm(rom[idx-2:idx+8], idx-2):
                if disasm_insn.address <= idx < disasm_insn.address + disasm_insn.size:
                    print(f"  0x{disasm_insn.address:06X}: {disasm_insn.mnemonic:10s} {disasm_insn.op_str}  [ref to 0x{target:08X}]")
                    break
            idx += 1

    # Scan for the actual adapter init/communication routines
    # Look for code that follows the "ADAPTER INITIALIZED" / "ADAPTER NOT INITIALIZED" strings
    print("\n\n=== ADAPTER INIT ROUTINE SEARCH ===")

    # The string "ADAPTER NOT INITIALIZED" at 0xAE00 and "ADAPTER INITIALIZED" at 0xAE1C
    # suggest there's an init check. Let's find the code that branches based on adapter state.

    # Search for the diagnostic strings area
    diag_start = rom.find(b"SegaChannel Remote Diagnostic")
    if diag_start >= 0:
        print(f"\n  'SegaChannel Remote Diagnostic' at 0x{diag_start:06X}")
        # Scan backwards to find the function that uses this
        # Look for references
        for scan_addr in [diag_start]:
            addr_bytes = struct.pack('>I', scan_addr)
            ref = rom.find(addr_bytes)
            while ref >= 0 and ref < len(rom):
                if ref != scan_addr:
                    print(f"  Referenced at 0x{ref:06X}")
                    # Show surrounding code
                    ctx_start = max(0, ref - 32)
                    for disasm_insn in md.disasm(rom[ctx_start:ref+48], ctx_start):
                        print(f"    0x{disasm_insn.address:06X}: {disasm_insn.mnemonic:10s} {disasm_insn.op_str}")
                ref = rom.find(addr_bytes, ref + 1)

    # Let's also look for the actual DRAM addressing pattern
    # The Sega Channel adapter mapped DRAM starting at specific addresses
    # Check for patterns like lea $xxxxxx, An where x is in cart range
    print("\n\n=== POTENTIAL DRAM BASE POINTER LOADS ===")

    # Scan raw bytes for LEA instructions (opcode 41F9 = lea $abs.l, a0, etc)
    # LEA $abs.l, An = 0100 nnn 111 111001 = 41F9, 43F9, 45F9, 47F9, 49F9, 4BF9, 4DF9, 4FF9
    lea_opcodes = [0x41F9, 0x43F9, 0x45F9, 0x47F9, 0x49F9, 0x4BF9, 0x4DF9, 0x4FF9]

    for offset in range(0, len(rom) - 6, 2):
        opcode = struct.unpack('>H', rom[offset:offset+2])[0]
        if opcode in lea_opcodes:
            addr = struct.unpack('>I', rom[offset+2:offset+6])[0]
            if 0x400000 <= addr <= 0x7FFFFF:
                reg_num = (opcode >> 9) & 7
                print(f"  0x{offset:06X}: lea $0x{addr:08X}, a{reg_num}")
                # Show context
                ctx_start = max(0, offset - 8)
                for disasm_insn in md.disasm(rom[ctx_start:offset+24], ctx_start):
                    marker = " <---" if disasm_insn.address == offset else ""
                    print(f"    0x{disasm_insn.address:06X}: {disasm_insn.mnemonic:10s} {disasm_insn.op_str}{marker}")
                print()

    # MOVEA.L #imm32, An = 0010 nnn 001 111100 = 207C, 227C, 247C, 267C, 287C, 2A7C, 2C7C, 2E7C
    movea_opcodes = [0x207C, 0x227C, 0x247C, 0x267C, 0x287C, 0x2A7C, 0x2C7C, 0x2E7C]

    for offset in range(0, len(rom) - 6, 2):
        opcode = struct.unpack('>H', rom[offset:offset+2])[0]
        if opcode in movea_opcodes:
            addr = struct.unpack('>I', rom[offset+2:offset+6])[0]
            if 0x400000 <= addr <= 0x7FFFFF:
                reg_num = (opcode >> 9) & 7
                print(f"  0x{offset:06X}: movea.l #$0x{addr:08X}, a{reg_num}")
                # Show context
                ctx_start = max(0, offset - 8)
                for disasm_insn in md.disasm(rom[ctx_start:offset+24], ctx_start):
                    marker = " <---" if disasm_insn.address == offset else ""
                    print(f"    0x{disasm_insn.address:06X}: {disasm_insn.mnemonic:10s} {disasm_insn.op_str}{marker}")
                print()

    # Also check MOVE.L #imm32, Dn for potential address constants
    # MOVE.L #imm32, Dn = 0010 nnn 000 111100 = 203C, 223C, 243C, 263C, 283C, 2A3C, 2C3C, 2E3C
    movel_opcodes = [0x203C, 0x223C, 0x243C, 0x263C, 0x283C, 0x2A3C, 0x2C3C, 0x2E3C]

    for offset in range(0, len(rom) - 6, 2):
        opcode = struct.unpack('>H', rom[offset:offset+2])[0]
        if opcode in movel_opcodes:
            addr = struct.unpack('>I', rom[offset+2:offset+6])[0]
            if 0x400000 <= addr <= 0x7FFFFF:
                reg_num = (opcode >> 9) & 7
                print(f"  0x{offset:06X}: move.l #$0x{addr:08X}, d{reg_num}")
                ctx_start = max(0, offset - 8)
                for disasm_insn in md.disasm(rom[ctx_start:offset+24], ctx_start):
                    marker = " <---" if disasm_insn.address == offset else ""
                    print(f"    0x{disasm_insn.address:06X}: {disasm_insn.mnemonic:10s} {disasm_insn.op_str}{marker}")
                print()

    print("\n=== SCAN COMPLETE ===")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        rom_path = "analysis/Sega Channel menu data/Sega Channel Guy/Canada Menu Demo December 1995.BIN"
    else:
        rom_path = sys.argv[1]

    deep_scan(rom_path)
