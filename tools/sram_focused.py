"""
Focused SRAM control analysis.
We know from the first scan:
- $A130F0 references at: 0x5DAC, 0x5E10, 0x5E2E, 0xFA4C, 0xFAE8, 0xFC28, 0x186C8E
- The key SRAM write is at 0x5E08 (lea $200001)
- Subroutines at 0x569E, 0x56C0, 0x56E2, 0x5706 handle adapter comms

Let's disassemble ALL of these thoroughly plus the surrounding functions.
"""

import struct
import sys
from capstone import *

def load_rom(path):
    with open(path, 'rb') as f:
        return f.read()

def disasm_at(rom, md, start, length, label=""):
    data = rom[start:start+length]
    if label:
        print(f"\n{'='*60}")
        print(f"  {label}")
        print(f"{'='*60}")
    for insn in md.disasm(data, start):
        marker = ""
        op_lower = insn.op_str.lower()
        if '$a130f' in op_lower:
            marker = "  <<< BANK SWITCH"
        elif '$200001' in op_lower or '$200000' in op_lower:
            marker = "  <<< SRAM"
        elif insn.mnemonic in ('bsr', 'jsr'):
            marker = f"  → call"
        elif insn.mnemonic in ('rts', 'rte'):
            marker = "  ──── return"
        print(f"  {insn.address:06X}: {insn.bytes.hex():16s} {insn.mnemonic:10s} {insn.op_str}{marker}")

def main():
    rom_path = sys.argv[1] if len(sys.argv) > 1 else "analysis/Sega Channel menu data/Sega Channel Guy/Canada Menu Demo December 1995.BIN"
    rom = load_rom(rom_path)
    md = Cs(CS_ARCH_M68K, CS_MODE_BIG_ENDIAN)
    md.detail = True

    print("=" * 70)
    print("  SRAM CONTROL PROTOCOL - FOCUSED ANALYSIS")
    print("=" * 70)

    # 1. The adapter comm subroutines (called from the adapter area)
    # These are the low-level I/O primitives
    disasm_at(rom, md, 0x5690, 0x120, "ADAPTER I/O SUBROUTINES ($5690-$57B0)")

    # 2. The full adapter communication area
    disasm_at(rom, md, 0x5800, 0x300, "ADAPTER COMMUNICATION ($5800-$5B00)")

    # 3. The game boot / data copy sequence
    disasm_at(rom, md, 0x5B00, 0x100, "PRE-BOOT AREA ($5B00-$5C00)")
    disasm_at(rom, md, 0x5C00, 0x0E0, "GAME BOOT SEQUENCE ($5C00)")

    # 4. The DRAM management area (contains $A130F0 accesses)
    disasm_at(rom, md, 0x5DA0, 0x0A0, "DRAM / BANK SWITCH ($5DA0-$5E40)")

    # 5. The other $A130F0 references at 0xFA4C, 0xFAE8, 0xFC28
    disasm_at(rom, md, 0xFA00, 0x100, "ADAPTER CONTROL BLOCK 2 ($FA00)")
    disasm_at(rom, md, 0xFAC0, 0x080, "ADAPTER CONTROL BLOCK 3 ($FAC0)")
    disasm_at(rom, md, 0xFC00, 0x080, "ADAPTER CONTROL BLOCK 4 ($FC00)")

    # 6. The reference at 0x186C8E (deep in the upper ROM)
    disasm_at(rom, md, 0x186C60, 0x080, "ADAPTER CONTROL BLOCK 5 ($186C60)")

    # 7. The diagnostic routines that read adapter state
    disasm_at(rom, md, 0x3700, 0x200, "DIAGNOSTIC / ADAPTER STATE READ ($3700)")
    disasm_at(rom, md, 0x3900, 0x200, "DIAGNOSTIC CONTINUED ($3900)")
    disasm_at(rom, md, 0x3B00, 0x200, "DIAGNOSTIC CONTINUED ($3B00)")
    disasm_at(rom, md, 0x3D00, 0x200, "DIAGNOSTIC / GAME_ID AREA ($3D00)")

    # 8. Let's check what calls the adapter I/O subs
    print(f"\n\n{'='*70}")
    print(f"  CROSS-REFERENCES TO ADAPTER SUBROUTINES")
    print(f"{'='*70}")

    # Search for JSR/BSR to our known subroutines
    targets = {
        0x569E: "adapter_read_byte_1",
        0x56C0: "adapter_read_byte_2",
        0x56E2: "adapter_write_cmd",
        0x5706: "adapter_write_data",
        0x5DAC: "adapter_init",
        0x5DBA: "dram_fill",
        0x5E08: "sram_write",
    }

    for target_addr, name in targets.items():
        print(f"\n  References to {name} (0x{target_addr:06X}):")
        # JSR absolute long: 4EB9 xxxx xxxx
        jsr_pattern = struct.pack('>HI', 0x4EB9, target_addr)
        idx = 0
        refs = []
        while True:
            idx = rom.find(jsr_pattern, idx)
            if idx < 0:
                break
            refs.append(('JSR', idx))
            idx += 1

        # BSR.W (16-bit displacement): 6100 xxxx
        # BSR.B (8-bit displacement): 61xx
        # Need to check all BSR instructions for matching target
        for offset in range(0, min(len(rom) - 4, 0x20000), 2):
            word = struct.unpack('>H', rom[offset:offset+2])[0]
            if word == 0x6100:  # BSR.W
                disp = struct.unpack('>h', rom[offset+2:offset+4])[0]
                dest = offset + 2 + disp
                if dest == target_addr:
                    refs.append(('BSR.W', offset))
            elif (word & 0xFF00) == 0x6100 and (word & 0xFF) != 0:  # BSR.B
                disp = (word & 0xFF)
                if disp & 0x80:
                    disp = disp - 256
                dest = offset + 2 + disp
                if dest == target_addr:
                    refs.append(('BSR.B', offset))

        for ref_type, ref_addr in sorted(refs, key=lambda x: x[1]):
            print(f"    {ref_type} at 0x{ref_addr:06X}")

    # 9. Analyze the decompression engine more deeply
    disasm_at(rom, md, 0xB5E0, 0x120, "DECOMPRESSION ENGINE ($B5E0)")

    # 10. Check what the adapter state structure looks like
    # A5 appears to be the adapter state base pointer
    print(f"\n\n{'='*70}")
    print(f"  A5 STATE STRUCTURE FIELDS")
    print(f"{'='*70}")

    # Find all (aN) with displacement instructions referencing common fields
    a5_fields = {}
    for offset in range(0, min(len(rom), 0x20000), 2):
        data = rom[offset:offset+8]
        instrs = list(md.disasm(data, offset))
        for insn in instrs:
            if insn.address == offset and '(a5)' in insn.op_str:
                # Extract displacement
                import re
                m = re.search(r'\$([0-9a-fA-F]+)\(a5\)', insn.op_str)
                if m:
                    disp = int(m.group(1), 16)
                    if disp not in a5_fields:
                        a5_fields[disp] = []
                    a5_fields[disp].append((offset, f"{insn.mnemonic} {insn.op_str}"))

    print(f"\n  Found {len(a5_fields)} unique A5 offsets")
    for disp in sorted(a5_fields.keys()):
        refs = a5_fields[disp]
        print(f"\n  $0x{disp:04X}(a5) — {len(refs)} references:")
        for ref_addr, ref_instr in refs[:5]:
            print(f"    0x{ref_addr:06X}: {ref_instr}")
        if len(refs) > 5:
            print(f"    ... and {len(refs)-5} more")

    print("\n" + "=" * 70)
    print("  ANALYSIS COMPLETE")
    print("=" * 70)

if __name__ == '__main__':
    main()
