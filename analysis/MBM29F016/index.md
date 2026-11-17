---
title: MBM29F016 notes
---

## 2026-11-17

Most of these chips held one byte lane of a wider bus, not a whole image. Each such dump holds every 2nd or 4th byte of the data the CPU saw. That makes text look like scattered letters and keeps code from disassembling cleanly until the other lanes are found.

### SII NS-2482 bank: dumps 3, 5 and 4

Dumps 3, 5 and 4 are byte lanes 0, 1 and 2 of one 8 MB, 32-bit flash bank from a Seiko Instruments NS-2482 Multi Access Server (68040 with an MC68360 QUICC, NS-OS 3.1, software dated 1998-08-31).

| Lane | Data bits | Dump |
| --- | --- | --- |
| 0 | D31–D24 | 3 |
| 1 | D23–D16 | 5 |
| 2 | D15–D8 | 4 |
| 3 | D7–D0 | not in the collection |

Evidence:

- Every 64 KB sector starts with a unit header (magic `24 11 00 80`). In sector 0 and in unused units, the unit number at +0x24 equals 4 × sector + lane. Sector 0 reads 0, 1 and 2 across dumps 3, 5 and 4, and sector 31 reads 0x7C, 0x7D and 0x7E.
- Interleaving sector 0 of dumps 3, 5 and 4 in that order, lane 0 first, gives readable boot-loader text with every fourth character missing.
- No unit number ending in lane 3 appears on any of the three chips, and no other dump has the `24 11` header.

Sector 0 is striped across all four chips. The other sectors are whole 64 KB file-system units stored on a single chip, so most file data can be read from one dump without interleaving. File-system block = unit × 127 + (block − 1); see dump 5.

Units shared between chips:

- Units 0x0E, 0x49 and 0x4E have identical bodies in dumps 4 and 5.
- Unit 0x48 in dump 5 (0x100000) holds the same data as unit 0x48 in dump 3 (0x120000), shifted 0x400 bytes later. Both contain the `pocvup` header.
- Unit 0x42 appears in dumps 3 and 4 with different bodies. The dump 3 agent also reported units 0x48 and 0x54 on two chips with different bodies. The overlaps are probably old and new copies left by the flash file system's wear levelling. Comparing the generation field at +0x26 in each pair would show which copy is current.

The missing lane 3 matters less than it might, because unit 0x49 (on dumps 4 and 5) holds a linear copy of the `POC-IDL Ver 3.0` loader. Its length and byte-sum trailer check out. The striped loader in sector 0 can be fully rebuilt from that copy.

### Other partial chips

Each of these is one lane of a bus whose other chips are not in the collection:

- **Dump 6:** one lane of a 32-bit 68020-class firmware bank, probably lane 3 (D7–D0). It has a 14-record directory at 0x000000 and four files that look like XMODEM downloads. The partner lanes would start with the same sector-0 directory.
- **Dump 7:** the low byte (D7–D0) of a 16-bit, 4 MB Hitachi SH bank from a Japanese car-navigation unit, about 1997. The partner chip should start with `AA AA AA AA` header markers. Interleave it with this one, partner byte first.
- **Dumps 8 and 9:** each is one lane of a 32-bit bank on the same kind of board, almost certainly with the same firmware. See below.

### Dumps 8 and 9: same board type, different banks

Both chips hold one byte lane (every fourth byte) of a 32-bit bank, and both have data bits D0 and D2 swapped relative to the CPU. The swap is probably in the board wiring, since other dumps read on the same reader need no swap.

The evidence that they are related comes from dump 9's analysis:

- The D0/D2 bit-correlation signature is identical.
- Byte-frequency profiles of the two compressed blocks correlate at 0.72–0.79.
- Dump 9's text block at 0x0010D3 shares byte-identical lane fragments with dump 8's diagnostic records, such as `hdurh:wl+/hp` at 8:0x10D8F4 and 8:0x112B3D. So both chips sit at the same lane position.

They are not lanes of the same bank, because their layouts differ:

- Dump 9 is compressed from 0x00113B to the end of the chip.
- Dump 8 has about 1 MB of compressed data, then text records, then erased space from 0x114563.

The two agents read this differently. The dump 8 agent concluded that no other lane of its bank is in the collection, which still holds. The dump 9 agent suggested dump 9 might be bank 0 and dump 8 bank 1 of a single board, with the compressed image continuing from one to the other. That is unproven, because the bit bias differs (0.539 in dump 8's first sectors against 0.515 at the end of dump 9). Two things would settle it:

- Decompressing across the boundary from the end of dump 9 into the start of dump 8.
- Finding the other three lanes of either bank.

None of the partial chips above (dumps 6–9) is the missing lane 3 of the NS-2482 bank, since none has the `24 11` unit header.

### Complete images

- **Dump 1:** a whole byte-wide image of Hitachi RAID300 disk-controller microcode. It is unrelated to the other dumps.
- **Dump 2:** a whole image of a GBK font flash for a text terminal. It holds only one column slice of its 24-row font, so the rest of that font was on other chips that are not here.

### What to look for in new dumps

- A `24 11 00 80` header with unit numbers ≡ 3 (mod 4) would be NS-2482 lane 3.
- A sector-0 directory with `A1`/`S1`/`X0` records would be a lane partner for dump 6.
- `AA AA AA AA` at offset 0 together with SH opcode high bytes would be dump 7's partner.
