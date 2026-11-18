---
title: SII NS-2482 flash disk, unit B
summary: Chips 0 and 1 of one NS-2482 unit's 8 MB flash disk. Together they rebuild half of its logical volume, 77 complete files from the 1999-03-25 06:11 update and the upper 16 bits of every word of the 2nd Boot program.
status: done
tags: [32-bit, big-endian, 68040, filesystem, flash-translation-layer]
updated: 2026-11-18
model: claude-opus-5-5
members: [MBM29F016A/3, MBM29F016A/13]
---

MBM29F016A/3 and MBM29F016A/13 are chips 0 and 1 of the four-chip, 8 MB flash disk of one Seiko Instruments NS-2482 Multi Access Server ("unit B"). The disk is used in two ways. Physical sector 0 of every chip holds one byte lane of a 32-bit-interleaved boot program. Everything else is a flash translation layer of 64 KB units, each chip a linear stream, carrying a small Unix-like file system. Three things tie the pair together. First, the 64 logical units on the two chips never collide, and between them they give exactly the residues 0 and 1 mod 4 of the factory layout. Second, the inode table on 13 (logical unit 0x09) points into units on 3 and 13 with the correct sizes, and all 77 files that lie entirely on these two chips reassemble cleanly. Third, one executable, `/share/initwan.r` (inode 571), starts on chip 3 and ends on chip 13: a `BSR.L` opcode at the last word of 3:0x15FFFE takes its displacement from the first bytes of 13:0x150200. Interleaving the two boot lanes gives complete high 16-bit words of 68040 code (`F498` CINVA IC, `4E7A`/`4E7B` MOVEC, `61FF`, `4E75`) and half-readable boot messages.

## Layout

| Bank | Lane | Data bits | Dump | Chip index | Factory logical units |
|---|---|---|---|---|---|
| 0 | 0 | D31-D24 | MBM29F016A/3 | 0 | 4*sector+0 |
| 0 | 1 | D23-D16 | MBM29F016A/13 | 1 | 4*sector+1 |
| 0 | 2 | D15-D8 | missing | 2 | 4*sector+2 |
| 0 | 3 | D7-D0 | missing | 3 | 4*sector+3 |

The data is spread across the chips in two different ways.

- **Boot program, byte-interleaved.** Chip offsets 0x000400-0x003877 of sector 0 on each chip form one lane of a 32-bit image. Bank offset = 4 × chip offset + lane, so this area covers bank offsets 0x1000-0xE1DF. 3 ends its lane at 3:0x003875 and 13 at 13:0x003874. The lane data is byte-identical to the lane 0 copy on MBM29F016A/12 and the lane 1 copies on 5 and 17, as recorded in the relation `ns2482-ipl-lanes`.
- **Flash disk, unit-striped.** Each 64 KB physical sector is one erase unit. It has a 512-byte header (`24 11 00 80 …`, logical unit number at +0x24) and 127 blocks of 512 bytes. A disk block number *n* is found at logical unit *n* div 127, block *n* mod 127. When the disk was formatted, units were dealt round-robin to the four chips. Wear levelling has since moved 36 of the 64 units held here. This pair holds logical units 00, 01, 04, 05, 09, 0C, 0D, 0F, 13, 15, 19, 1A, 1C-1F, 21, 25, 26, 29, 2A, 2D, 2F, 31, 33, 35, 36, 39-3B, 3F, 40, 42-44, 47, 48, 4A, 4C, 4E, 4F, 51, 53-55, 59, 5B and 5C, plus the never-used units 60, 64 … 7C (chip 0) and 61, 65 … 7D (chip 1).

![Logical unit map](images/logical-unit-map.png)

| Logical units | Role | Where |
|---|---|---|
| 00-07 | Raw boot area (512 KB, outside the file system). Physical sectors 0-1 of all four chips | 00, 04 on 3; 01, 05 on 13 |
| 08 | Superblock, inode and block bitmaps, inodes 0-479 | missing (expected on chip 3) |
| 09-0D | Rest of the inode table (blocks 0x3FF-0x6F1) | 09 on 13:s15, 0C on 3:s03, 0D on 13:s03 |
| 0E-7F | Data blocks 0x6F2-0x3F00 | 57 of 114 units here (16 of them never used) |

## Findings

- **Logical units are complementary.** No logical unit number occurs on both chips. Both chips have exactly one copy of every factory-fresh unit in their residue class: units 60-7C on 3:s24-s31 and 61-7D on 13:s24-s31, all with erase count 1 and zero payload. Neither chip holds a spare (transfer) unit with number FFFF, so the volume's spare must be on chip 2 or 3.
- **Inode table on 13, data on both.** Logical unit 0x09 at 13:0x0F0200 holds inodes 480-590, which are the files of the last software update. Every one has change time 1999-03-25 06:11 UTC (`36F9D37A` at +0x1A) and second time 1998-08-31 06:22-06:23 at +0x16. The block count is a u16 at +0x20. Pointers start at +0x22: 18 direct, then single-indirect at +0x6A and double-indirect at +0x6E. These 110 regular files need 2,697 data blocks. The two chips hold 1,122 of them (42 %), and 77 of the 110 files are complete.
- **Cross-chip checks.** Every complete `AB CD 02 00` executable has a file length field at +0x30 equal to its inode size, and every one ends in the `… FF FF FF FF` terminator of its relocation table. Seventeen executables check out, including `/sbin/arp` (inode 529, 12,800 bytes, first block 3:0x086400, indirect block 3:0x088800) and `/share/initwan.r` (inode 571, 41,080 bytes). initwan.r runs from 3:0x15B800 to the end of logical unit 0x54 at 3:0x15FFFF. It continues at logical unit 0x55, 13:0x150200, and ends at 13:0x155C00. The opcode `61 FF` at 3:0x15FFFE takes its 32-bit displacement `FF FF D4 EA` from 13:0x150200, followed by `58 8F` (`ADDQ.L #4,SP`). Logical unit 0x1D (3:s07) also continues into 0x1E (13:s07): `… 50 8F` at 3:0x07FFFE, then `2E 00 60 4C` at 13:0x070200.
- **Recovered files.** All 46 per-port setup files of the update are complete, in logical unit 0x4A at 3:0x080200-0x0863FF. They are inodes 483-528: 5 `# High Super Digital (HSD) setup`, 5 `#<TAB><Layer2 Configuration File>`, 5 `# PPP setup`, 3 `# PRI port (FR & HSD) setup` and 28 `# Frame Relay setup` files, in a repeating set per WAN directory. Also complete:
  - `init.conf`, the start-up script (inode 569, 7,357 bytes, 3:0x154400). It binds `udp`, `tcp`, `ip`, `ospf`, `en960`, `pty`, `e2prom`, `MCardI`, `enIpx`, `ipxr`, `ddp`, `tn` and other drivers, then runs `/bin/date`, `/sbin/prom -0`, `/sbin/cpuinfo` and `/sbin/show /version`. It contains a commented-out route to the host `sii`.
  - `lanconfig` (572), `reload` (552), `re-analyze WAN`, `re-assign TS(Time Slot)` and `re-load FR` (579-581), the WAN set-up scripts 531, 533, 542, 559, 561 and 564-566, and the executables `prom` (550), `pppstat` (549), `statpr` (557), `snstatis` (560), `stattime` (562), `vlsetup` (563), `fscopy` (567), `libftp.r` (573) and `setupwan.r` (582).
- **Directory blocks.** Six directory blocks are on these chips. They are 32-byte entries: a u32 inode number and a 28-byte name.

  | Location | Directory | Entries |
  |---|---|---|
  | 3:0x049600 | `/sbin` | `ls` … `rfree`, with the 1998 update's `mkrd`, `ospfdrvsetup`, `ospfflagchg`, `ospfrdsts`, `page` as inodes 417-421 |
  | 13:0x06BE00 | `/driver` | `la.drv` … `spi.drv`, with update inodes 451-459 |
  | 3:0x0B3200, 3:0x0C4200 | `/share` | `initwan.r`=571, `lanconfig`=572, `libftp.r`=573, `libinet.r`=574, `libsetup.r`=575, `libtelnet.r`=576, `ospfd`=578, `setupwan.r`=582, `snmpd`=583 |
  | 3:0x0E6800, 3:0x0E6A00 | Setup directory (inode 404) | `common`, `default`, then `init.conf.local` |

  The `/share` entries name the 1999 executables, which cannot be named from 13's inode table alone.
- **Same install as unit A, different allocation.** Inodes 480-590 have the same 111 sizes as the table at 19:0x100200 (unit A). The first block pointer is exactly 2 higher on unit A for all 110 files with data. So the 1999 update wrote the same file set in the same order, starting two blocks earlier on this unit. Unit A's update ran on 1999-07-12, and this unit's ran on 1999-03-25.
- **Boot program, lanes 0 + 1.** Interleaving 3 and 13 gives the upper half of every 32-bit word from bank offset 0x1000. For 68k code, that is every other 16-bit instruction word, complete. The commonest words are `61FF` (226), `588F` (196), `4E75` (179), `2F0D`, `4FEF`, `4878`, `48E7`/`4CDF` and `42A7`, which is the profile of compiled 68020+ code. The start-up code has `4E7A` (MOVEC from control register) at bank offset 0x1018, `F498` (CINVA IC, 68040 only) at 0x1038, `203C 8000…` and `4E7B` (MOVEC to control register) at 0x105C. That fits the 68EC040 main CPU named by `cpuinfo` (3:0x08C7E4), with the MC68360 QUICC as a companion. Text comes out with two of every four characters:

  ```
  0036BC  ap··ec··#%··%s··R=··%0·· P··0x··8X··/b··tc··f.··
  0036EC  on··.2·· B··t ··rs··n ··2 ··ar··.b··t ··ra··te··
  003878  m.··oa··3r··Bo·· f··m ·· (·· %··X-··8X··OK··/b··
  003918  .-··. ··12··56··9A··DE··01··45··89··cd··.0··0X··
  00410C  ..··PO··ID··Ve··3.··..··..··..··..··N.··@.··H.··
  ```

  These are the lane 0 and 1 bytes of `Vect #%d %s SR=0x%04X PC=0x%08X`, `2nd Boot version 1.2 start.`, `load 3rd Boot from %s (%s %08X-%08X) OK.`, `0123456789ABCDEF` and `POC-IDL Ver 3.0`.
- **Per-lane byte at chip offset 0x1FF.** 3:0x0001FF is `78` and 13:0x0001FF is `FB`. The same values appear on the other chips of the same lane (12, and 5 and 17), so they belong to the boot image, not to the unit. At bank offset 0x7FC they form the upper half of a 32-bit word, `78 FB ·· ··`. This is probably a checksum or length word for the 2nd Boot program. 3:0x0003FC also holds `C3 46 DF FF` at the end of the partition record. That record (`flush(FLUSH-EEPROM boot/partition(boot=512k) 8M byte(erase block = 64Kbyte)`, 3:0x000200) exists only on chip 0.
- **Partition record block numbers.** The geometry words at 3:0x000280 list blocks 0x3F8, 0x9EC, 0x194D, 0x1D45, 0x1F41 and 0x1FC0. Each is the first block of logical unit 8, 20, 51, 59, 63 and 64. On this unit, units 51, 59 and 63 (13:0x0C0200, 13:0x120200, 13:0x040200) and 64 (3:0x0F0200) now hold ordinary file data: relocation records and 68k code. The list therefore no longer describes live metadata. It is probably the formatter's original placement.

![Coverage of the 1999 update's files](images/update-file-coverage.png)

## Device

**Seiko Instruments (SII) NS-2482 Multi Access Server, an ISDN/PRI, HSD and frame-relay WAN access router running NS-OS 3.1. Confidence: high.**

- Neither chip names the product. The name comes from unit A's chips (a `/version` text and the SNMP `SysDescr "SII Multi Access Server NS-2482."` on MBM29F016A/15).
- This pair carries the same software install. The boot lanes are byte-identical, and the inode table, file sizes and file order of the 1998-08-31 Ver 3.1 update and the later update match unit A's exactly.
- The start-up script refers to a host called `sii`.
- `cpuinfo` (3:0x08C7E4) and the boot code's CINVA/MOVEC sequence show a 68EC040 main CPU. The kernel and scripts drive MC68360 QUICC boards (`QMC.drv`, `QCH.drv`, `SI(QUICC Serial Interface)`).
- The group facts list only the MC68360 QUICC as CPU. The main processor is a 68EC040.

## Missing members

- **Chip 2 (lane 2, D15-D8).**
  - **Recognise it by:** `24 11 00 80` unit headers. Sector 0 lane data from 0x000400 begins `46 7A 2A 40 61 03`. Factory-fresh units are numbered 4*sector+2 (62, 66 … 7E in sectors 24-31). No logical unit number is shared with 3 or 13.
  - **What it adds:** the low byte of the upper 16 bits of every boot-program word, which would make the 2nd Boot text three-quarters readable.
  - **What it would show:** about a quarter of the data blocks of the update's files. This includes the start of `/share/libinet.r` (574, 41 of 74 blocks missing) and parts of `ospfd` (578) and `snmpd` (583).
- **Chip 3 (lane 3, D7-D0).**
  - **Recognise it by:** sector-0 lane beginning `52 71 A4 00 28 5A`. Factory-fresh units are numbered 4*sector+3. It probably holds logical unit 0x08: the superblock with magic `00011954` at block 0x3F9, the bitmaps, and inodes 0-479 with change times around `36F9D3xx`.
  - **What it adds:** the superblock and the older half of the inode table. Without them, the root directory and every file older than the 1999 update cannot be resolved. It also completes the boot program's 32-bit words.
- **Units not on any dumped chip.** Logical units 49, 4B, 4D, 50, 52, 56-58, 5A, 5D-5F hold the rest of the update. Unit 0x49 holds the first three update files (inodes 480-482). Unit 0x5F holds `/version` (inode 589, block 0x2F66, 70 bytes), which would give this unit's exact version string. The spare unit (FFFF) should also be on chip 2 or 3.

## Open questions

- **Bytes at 0x1FF and 0x3FC.** What are the bank-offset 0x7FC word (`78 FB ·· ··`) and `C3 46 DF FF` at 3:0x3FC? With lanes 2 and 3, test them as a checksum or length of the 2nd Boot image (bank offset 0x1000 to about 0xE1DF).
- **Inode field +0x76.** On this unit it holds times from 1999-03-17 to 1999-03-29, both before and after the 06:11 change time on 03-25. Is it an access time, or a time carried in from the update package? Compare it across units once more inode tables are available.
- **Setup directory inode 404.** It holds `common`, `default` and `init.conf.local`. Is it `/setup`, `/save/setup` or `/usr/setup`? Its parent entry is in logical unit 08, which is missing.
- **Partition-record block list.** What is the purpose of the list at 3:0x000280? The flash driver (`MCardI.drv`, or `e2prom`/`pt`) would need to be disassembled to see whether it is still read.
- **Next step.** Load the complete recovered executables, for example `prom` (550) and `fscopy` (567), at their section addresses in a 68k disassembler. They should show the flash-disk driver interface and the meaning of the unit-header fields +0x26 and +0x2C.

## Method

I mapped each chip's 32 unit headers to logical unit numbers and built a block lookup: logical block *n* is at logical unit *n* div 127, offset 0x200 + (*n* mod 127) × 0x200. I parsed the 128-byte inodes in logical unit 0x09 (13:0x0F0200). Each file was reassembled from its direct and indirect pointers, with a placeholder for blocks on missing units. Executables were checked by comparing header length to inode size and by their relocation terminator. I scanned all blocks for 32-byte directory entries. Sector 0 of both chips was interleaved at stride 4 (lane 0 = 3, lane 1 = 13) from bank offset 0x1000, and the high 16-bit words were counted. The first inode pointers were compared with unit A's table at 19:0x100200. All work used `python3 -I` in a temporary directory, and the images were drawn with Pillow.
