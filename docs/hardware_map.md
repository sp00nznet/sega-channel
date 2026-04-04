# Sega Channel Adapter - Complete Hardware Map

**Source ROM:** Canada Menu Demo December 1995 (2MB)  
**Developer:** Pacific SoftScape Inc.  
**Copyright:** (C)T-XX 1994.JAN  

---

## 1. Adapter Overview

The Sega Channel adapter is a cartridge-slot device containing:
- **4MB DRAM** mapped into the Genesis cartridge address space ($000000-$3FFFFF)
- **Bank switching registers** at $A130F0-$A130FA  
- **Data port** at $A13040  
- **Status register** at $A13042  
- **Control registers** at $A13010-$A13032  
- **SRAM/control space** at $200000-$203FFF (accessible when $A130F0 = 1)

The adapter receives data from the cable headend, stores it in DRAM, and the
Genesis CPU accesses it as if it were a normal cartridge ROM.

---

## 2. Register Map

### Bank Switching Registers ($A130F0-$A130FA)

These 6 registers control which 512KB bank of DRAM appears in each 512KB
window of the Genesis address space. Standard SSF2-style bank switching.

| Register | Purpose | Init Value |
|----------|---------|------------|
| $A130F0  | Bank 0 ($000000-$07FFFF) + SRAM mode flag | 0 |
| $A130F2  | Bank 1 ($080000-$0FFFFF) | 1 |
| $A130F4  | Bank 2 ($100000-$17FFFF) | 2 |
| $A130F6  | Bank 3 ($180000-$1FFFFF) | 3 |
| $A130F8  | Bank 4 ($200000-$27FFFF) | 4 |
| $A130FA  | Bank 5 ($280000-$2FFFFF) | 5 |

**Special behavior of $A130F0:**
- Value 0 = Normal mode (DRAM bank 0 visible)  
- Value 1 = SRAM/Control mode ($200000-$203FFF maps to adapter control SRAM)

The ROM always initializes all 6 registers in sequence before accessing
DRAM data:
```asm
move.w  #$0, $a130f0.l    ; Bank 0
move.w  #$1, $a130f2.l    ; Bank 1
move.w  #$2, $a130f4.l    ; Bank 2
move.w  #$3, $a130f6.l    ; Bank 3
move.w  #$4, $a130f8.l    ; Bank 4
move.w  #$5, $a130fa.l    ; Bank 5
```

### Data Transfer Port ($A13040)

The adapter's **data input port**. The menu ROM writes game data TO the adapter
through this register. Used in the game loading sequence:

```asm
lea.l   $a13040.l, a0      ; Data port address
movea.l $52(a5), a1         ; Source data pointer
move.w  #$1fff, d1          ; 8192 words = 16KB per transfer
loop:
move.w  (a1)+, (a0)         ; Write word to adapter data port
dbra    d1, loop
```

Each call transfers 16KB ($2000 words) through the port. The $4c(a5) counter
tracks how many 16KB blocks remain.

### Status/Verify Register ($A13042)

Read from this register after data transfer to verify completion:

```asm
move.l  $a13042.l, d0       ; Read status
swap    d0                    ; Swap bytes for comparison
cmp.l   $4e(a5), d0          ; Compare against expected value
beq     done                  ; Match = transfer complete
bset.b  #$0, $2c(a5)         ; Mismatch = set retry flag
```

### Control Registers ($A13010-$A13032)

| Register | Purpose |
|----------|---------|
| $A13010  | Unknown control |
| $A13012  | Unknown control |
| $A13022  | Unknown control |
| $A13024  | Unknown control (frequently accessed) |
| $A13026  | Unknown control |
| $A13030  | Status/control |
| $A13032  | Status/control (written with ORI #$10 during init) |
| $A13034  | Unknown control |

### SRAM Control Space ($200000-$203FFF)

When $A130F0 = 1, the $200000 range maps to adapter SRAM. The ROM uses this
for bulk writes:

```asm
; SRAM Write Routine ($5E08)
tst.b   $841c.w              ; Check if SRAM write needed
bne     do_write
rts                           ; Nothing to write

do_write:
move.w  #$1, $a130f0.l       ; Enter SRAM mode
move.b  $841d.w, d1           ; Get byte value to write
lea.l   $200001.l, a0         ; SRAM base (odd bytes only)
move.w  #$1fff, d0            ; 8192 iterations
fill_loop:
move.b  d1, (a0)              ; Write byte
addq.w  #$2, a0               ; Skip to next odd byte
dbra    d0, fill_loop
clr.w   $a130f0.l             ; Exit SRAM mode
rts
```

**Key detail:** Only ODD bytes are written ($200001, $200003, $200005...).
This is the standard 8-bit SRAM interface on the Genesis (D0-D7 on odd addresses).

---

## 3. Communication Protocol

### Comm Buffer ($FFE1A8, indexed by $FFE2A8)

The menu ROM doesn't talk to the adapter directly for most operations. Instead,
it uses a **256-byte communication buffer** in 68K RAM at $FFE1A8.

Four subroutines manage this buffer:

| Subroutine | Function | Description |
|------------|----------|-------------|
| $569E | `read_at(index)` | Set index to param, read byte from buffer[index] |
| $56C0 | `read_next()` | Increment index, read byte from buffer[index] |
| $56E2 | `write_at(index, byte)` | Set index to param, write byte to buffer[index] |
| $5706 | `write_next(byte)` | Increment index, write byte to buffer[index] |

These are C-calling-convention functions (params on stack via LINK/UNLK):

```c
// $569E - read_at
uint8_t read_at(uint16_t index) {
    comm_index = index;          // $FFE2A8
    return comm_buffer[index];   // $FFE1A8 + index
}

// $56C0 - read_next
uint8_t read_next() {
    comm_index++;
    return comm_buffer[comm_index];
}

// $56E2 - write_at
void write_at(uint16_t index, uint8_t byte) {
    comm_index = index;
    comm_buffer[index] = byte;
}

// $5706 - write_next
void write_next(uint8_t byte) {
    comm_index++;
    comm_buffer[comm_index] = byte;
}
```

### Command Protocol

The comm buffer uses a **command/response** model with indexed slots:

| Buffer Index | Purpose |
|-------------|---------|
| $00CC | Command register (read) |
| $01E1 | Status/command type |
| $01E2 | Command parameter |

**Game selection sequence** (from $5CFA):
```
1. Read buffer[$00CC] → must equal $01 (game select command)
2. Read buffer[$01E1] → if $FF, abort (no game)  
3. Read 4 bytes sequentially → 32-bit game data address
4. Copy game data from address to buffer
5. Write $FF to buffer[$01E1] (acknowledge/complete)
```

**Game boot sequence** (from $5C02):
```
1. Copy 1KB from adapter state ($FF8400) to $100000
2. Write game ID ($FF841A) to header at $1000FE
3. Copy comm buffer state to adapter
4. Send address bytes through write_at/write_next
5. Acknowledge with $FF at index $01E1
6. Disable interrupts (SR = $2700)
7. Request Z80 bus
8. Copy reset stub to $FF0000
9. Jump to $FF0000 → clears I/O → boots game
```

---

## 4. Adapter State Block ($FF8400-$FF8420)

This block in 68K RAM tracks the adapter's current state:

| Address | Size | Purpose |
|---------|------|---------|
| $FF8400 | Long | DRAM data base pointer |
| $FF8404 | Long | ROM size / DRAM capacity indicator |
| $FF8408 | Long | Game data offset |
| $FF840C | Word | Menu/channel control |
| $FF840E | Long | Expected data length |
| $FF8412 | Word | Direct header read flag (0 = read from DRAM) |
| $FF841A | Word | Game ID |
| $FF841C | Byte | SRAM write pending flag |
| $FF841D | Byte | SRAM write data value |
| $FF841E | Byte | Adapter mode/state |

### Capacity Check ($FF8404)

The ROM checks this value against $300000 (3MB boundary):
```asm
cmpi.l  #$300000, $8404.w
bls     normal_mode
subi.l  #$100000, d0    ; Adjust offset for >3MB ROMs
```

This suggests the adapter could handle different DRAM configurations
(3MB vs 4MB), with different data layouts for each.

---

## 5. Data Transfer Flow

### Loading a Game

1. **Bank Setup**: Initialize all 6 bank registers to linear mapping
2. **Read Header**: From DRAM at $FF8400 base, read game metadata
   - Word at offset 0: header size/skip value  
   - Long at offset 2: game data start address  
   - Long at offset $A: expected data size  
3. **Calculate Transfer**: 
   - Total data = game size / 2 (word count)
   - Blocks = total / $2000 (16KB blocks)
4. **Transfer Loop**:
   - Write 16KB blocks to data port $A13040
   - Decrement block counter $4c(a5)
   - Repeat until all blocks transferred
5. **Verify**: Read $A13042, compare against expected value
6. **Boot**: Execute game boot sequence at $5C02

### DRAM Fill / Test

The DRAM fill routine ($5DBA) writes a test pattern across all 4MB:
- Pattern: $A125A125
- Block size: 246 bytes ($F6)
- Advances through $56(a5) pointer
- Stops at $400000 (4MB boundary)
- Sets completion flag at bit 0 of $2c(a5)

---

## 6. Serial Port Usage

The ROM uses the Genesis serial port ($A10015-$A10019) for communication
with the adapter's tuner/demodulator:

```asm
; Serial init ($B638)
move.b  #$10, $a1000b.l     ; Set serial control
move.b  #$38, $a10019.l     ; Set serial rate/mode

; Serial transmit ($B5F2)
loop:
  rol.l   #$8, d0             ; Rotate next byte into position
  btst.b  #$0, $a10019.l     ; Wait for TX ready
  bne     loop
  move.b  d0, $a10015.l      ; Send byte

; Serial receive (HBlank INT handler at $B652)
  btst.b  #$1, $a10019.l     ; Check RX data available
  beq     done
  move.b  $a10017.l, (a0)    ; Read received byte into buffer
```

The serial port handles the **control channel** between the 68K CPU and the
adapter's cable tuner. This is how the menu ROM tells the adapter which
channel/frequency to tune to, and receives status updates.

**Receive buffer**: $FFE318 (256 bytes), indexed by $FFE418/$FFE41A

---

## 7. Architecture Summary

```
Cable TV Signal
     |
     v
[Adapter Tuner/Demod] <--serial--> [68K CPU via $A10015-$A10019]
     |
     v
[4MB DRAM] <--bus--> [Genesis cartridge slot]
     |                       |
     |-- $000000-$3FFFFF     |-- Bank regs: $A130F0-$A130FA
     |   (ROM/game data)     |-- Data port: $A13040
     |                       |-- Status:    $A13042
     |-- $200000-$203FFF     |-- Control:   $A13010-$A13034
         (SRAM when $A130F0=1)

[68K RAM $FF0000-$FFFFFF]
     |-- $FF8400: Adapter state block
     |-- $FFE1A8: Comm buffer (256 bytes)
     |-- $FFE2A8: Comm buffer index
     |-- $FFE318: Serial RX buffer
```

---

## 8. What We Need to Emulate

To build a working server-fed Sega Channel:

### Must Emulate:
1. **$A130F0-$A130FA** — Bank switching (SSF2 mapper style)
2. **$A130F0 = 1 mode** — SRAM overlay at $200000
3. **$A13040** — Data port (accept word writes, feed to DRAM)
4. **$A13042** — Status register (return transfer verification value)
5. **$A13032** — Control register (at minimum, accept ORI #$10)
6. **4MB DRAM backing store** — Fill with menu ROM + game data
7. **Adapter state block** — Populate $FF8400-$FF8420 with valid values
8. **Serial port** — Route to network layer for channel/game selection

### Can Stub:
- $A13010, $A13022, $A13024, $A13026, $A13030, $A13034 — Accept writes, return 0
- DRAM test responses — The fill routine can just work against normal RAM

### Server Protocol:
The server replaces the cable headend. It needs to:
1. Provide the menu ROM + SCMENU.BIN data (loaded into DRAM on startup)
2. Serve game catalog (replaces game guide BINs)
3. Stream ROM data on game selection (fills DRAM via data port)
4. Handle serial-channel commands (tune/status) via network
