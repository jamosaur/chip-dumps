---
title: SII NS-2482 flash disk, unit A
summary: Three of the four MBM29F016A chips of one NS-2482 unit's 8 MB flash disk; the rebuilt file system confirms chip 12 as lane 0 and the rebuilt boot sector shows a 68040/68060-class host CPU.
status: done
tags: [m68k, filesystem, flash-translation-layer, router, seiko-instruments]
updated: 2026-11-18
model: claude-opus-5-5
members: [MBM29F016A/12, MBM29F016A/19, MBM29F016A/15]
---

These three chips are lanes 0, 2 and 3 of the four-chip, 32-bit flash array in one Seiko Instruments (SII) **NS-2482** Multi Access Server. The array holds an 8 MB wear-levelled flash disk and a lane-split boot area. When the three chips' 64 KB units are placed by the logical-unit number in their headers, they rebuild 95 of the disk's 127 logical units. On that disk the superblock (on 15), the inode tables (on 15 and 19), the directories and the file data (on all three chips) agree with one another across chips. For example, the `/share` directory blocks on chip 12 list the inodes created by the 1999-07-12 update. Those inode records are on 19, and the files they describe start on 12 with matching lengths. That settles chip 12's place, which earlier rested only on the absence of clashes. Interleaving sector 0 of the chips rebuilds two boot programs, `2nd Boot version 1.2` and `POC-IDL Ver 3.0`. Their headers carry byte-sum checksums that match once the missing lane 1 is borrowed from another unit. The entry code issues MC68040 cache instructions, so the main processor is a 68040 or 68060, not the MC68360 itself.

## Layout

| Bank | Lane | Data bits | Dump | Unit numbers when never rewritten |
|---|---|---|---|---|
| 0 | 0 | D31–D24 | MBM29F016A/12 | 4 × sector + 0 |
| 0 | 1 | D23–D16 | missing | 4 × sector + 1 |
| 0 | 2 | D15–D8 | MBM29F016A/19 | 4 × sector + 2 |
| 0 | 3 | D7–D0 | MBM29F016A/15 | 4 × sector + 3 |

The data is spread in two different ways.

- **Boot area (sector 0 of each chip, chip offsets 0x000400–0x00387F).** This area is written as 32-bit linear memory, so bank offset = 4 × chip offset + lane. Chip offset 0x400 becomes bank offset 0x1000, and the area ends at bank offset 0xE1FF.
- **Flash disk (everything else).** Each chip is driven as its own byte-wide device. Every 64 KB sector is one erase unit: a 512-byte header (magic `24 11`, logical unit number at +0x24, erase count at +0x2C/+0x2E), then 127 data blocks of 512 bytes. Logical block = unit × 127 + block index. The formatter dealt units 0–127 round-robin across the four chips. Wear-levelling has since rewritten 58 of the 96 sectors on these three chips, and 55 of their 95 logical units no longer sit at their formatted position (bank map below). The volume has 127 logical units (0x00–0x7E) and exactly one spare (transfer) unit, at 12:0x130000. The superblock's data area ends at block 16,129 = 127 × 127, so no logical unit 0x7F exists. Chip 1 must therefore hold exactly the 32 numbers missing here, with no spare.

![Bank map](images/bank-map.png)

![Rebuilt logical disk](images/logical-disk.png)

## Findings

### The rebuilt flash disk

- **Volume parameters agree across chips.** The `xflush` driver label exists only on chip 0, at 12:0x0001FF (`xflush(FLUSH-EEPROM boot/partition(boot=512k) 8M byte(erase block = 64Kbyte)`). Its parameter longs at 12:0x000280 give 127 blocks per unit, 512-byte blocks and a 0x3F8-block (1016-block) boot partition. The superblock at 15:0x060400 (logical block 1017, magic `00011954`) starts the file system right after that partition: the boot block is 1016 and the superblock 1017. The inode bitmap (0x3FA), block bitmap (0x3FB, 4 blocks) and inode table (0x3FF, 0x2F3 blocks, 3020 inodes) follow.
- **Directory tree.** The root directory is inode 0 at 15:0x061000. Its two blocks are on two chips, 19:0x160200 (`admin bin boot.3rd bootconf driver etc init init.root mnt mnt2 mnt3 nsx.sys pocvup save`) and 15:0x1FB600 (`sbin setup share stand tmp usr version vup os_version`). Walking the tree from there reaches 433 of the 449 live inodes: 56 directories, 3 symlinks (`/setup` → `/tmp/setup`, `/etc` → `/tmp/etc`) and 374 regular files. The other 16 are named in the missing chip's blocks of `/admin`, `/driver` and `/sbin`. 234 files can be rebuilt completely from the three chips. 12 of them only because they span two chips, for example `/pocvup`, which starts on 12 and continues on 19.
- **Inode layout** (refined from the single-dump write-ups). +0x00 type (`0000` file, `0010` directory, `0020` symlink), +0x02 mode, +0x04 link count, +0x0A size, three Unix times at +0x12/+0x16/+0x1A, +0x20 data-block count, 18 direct pointers from +0x22, then a single-indirect pointer at +0x6A and a double-indirect pointer at +0x6E. The double-indirect pointer is needed to reach the 304 blocks of `/nsx.sys` and the 363 blocks of `/share/ospfd`.
- **Every block pointer into chip 12 checks out.**
  - Live files reference 1,331 data blocks on 12, and all of them are marked used in the block bitmap at 15:0x060800.
  - 23 of 23 files whose first block is on 12 start with an `AB CD 02 00` header whose length field (+0x30) equals the inode size. Examples are `/share/libftp.r` (16,944 bytes, 12:0x157A00) and `/share/vupd` (40,468 bytes, 12:0x177800).
  - The other 11 files that start on 12 begin with plain text.
  - 30 of 30 files whose last block is on 12 end exactly at the inode size, with zeros after.
  - As a control, chip 0 of unit B (`MBM29F016A/3`) was put in 12's place. It clashes with 19 and 15 on units 0x13, 0x1C, 0x42 and 0x4A, and fails 34 of the same checks: 15 tails, 18 text starts and 1 header.
- **Chip 12 carries data from the 1999-07-12 06:20 update.**
  - The `/share` directory (inode 17) has blocks at 12:0x0B3200, 12:0x0C4200 and 12:0x0E2000. They list `lanconfig`=572, `libftp.r`=573, `libinet.r`=574, `ospfd`=578, `snmpd`=583, `vupd`=584, `wanconfig`=585 and others. Those inode records are in the update's inode table on 19 (for example inode 573 at 19:0x103080). Their changed times are 1999-07-12 06:20 UTC, and their block pointers lead back to 12.
  - Unit B (chips 3 and 13) installed the same files two blocks earlier. All 77 blocks of update files on 12 that unit B's chips also hold are identical, block by block, to unit B's copies at unit B's own pointers, with no mismatch.
  - `/os_version` (inode 468, record at 15:0x06FA00) is the 25-byte text `NS-OS version 3.1 start.`, stored at 12:0x12F600. `/version` is on 19 at its inode's single block: `Communication Server NS-2482 System Software 1998.08.31 (Ver 3.1)`.
  - Inode 404 (15:0x06DA00) points to 12:0x0E6800. That block is the `/stand/setup` directory, whose `.` entry is 404 and whose `..` entry is 18 (`/stand`). The record on 15 and the block on 12 confirm each other.
- **The block bitmaps of unit A (15) and unit C (14) are bit-for-bit identical** (6,392 used blocks), and so are their 0–479 inode block lists. Block-level checks therefore cannot tell unit A from unit C. 12 is kept out of unit C by duplicate logical units: it holds units 0x43, 0x44, 0x48 and 0x52, which 14 also holds with identical content.

### The rebuilt boot area

- Interleaving 12, 19 and 15 at stride 4 in sector 0 gives readable 68k text with every fourth byte missing (lane 1 shown as `·`):

```
bank offset 0x36F0  .·nd ·oot·ver·ion·1.2·sta·t._·oot·par·met·r N·.
bank offset 0x3730  n·tia·ize·mem·ry ·ard·NG.·no ·ard·_in·tia·ize·me
bank offset 0x3870  F·ash·Rom·_lo·d 3·d B·ot ·rom·%s ·%s ·08X·%08·)
bank offset 0x4110  P·C-I·L V·r 3·0 _·___·___·___·__N·__@·NuH·.. ·._
bank offset 0xE0E0   ·lea· DP·&LO·_CC·TT ·eco·men·ati·n G·703·CCI·T
```

- Sector 0 of each chip position is identical across units (relation `ns2482-ipl-lanes`). Lane 1 was therefore borrowed from `MBM29F016A/13` (0x400 starts `42 F6 00 00 3C 00 7A 00`) to complete the picture. With it, the area is two programs with headers.
  - **Bank offset 0x1000, `2BFR` header.** The +0x06 u16 is 0x7A71, +0x08 is the length 0x2AA4, and +0x0C is 0x4000. The byte sum of the 0x2AA4 bytes from 0x1010 is exactly 0x7A71. The program is `2nd Boot version 1.2` (0x36F1). It reads `/bootconf`, initialises the memory card or flash ROM file system, and runs `load 3rd Boot from %s (%s %08X-%08X) OK.` (0x387B), meaning `/boot.3rd` on the flash disk.
  - **Bank offset 0x4000, `HPOC` header.** The fields are +0x14 start 0x4100, +0x18 length 0xA0D8 and +0x12 u16 0xA6BE. The byte sum of 0x4100–0xE1D7 is 0x2FA6BE, whose low 16 bits are 0xA6BE. The program is `POC-IDL Ver 3.0` (0x4110), with a 68020/030/040 exception-name table and T1/E1 line-status text (0xDFD6–0xE164). Bank offsets 0x4100–0xE1D8 are byte-identical to `/pocvup` bytes 0x11D8–0xB2B0. `/pocvup` is a file that the rebuilt file system recovers from 12 (4 blocks) and 19 (92 blocks), so the flash updater carries this boot program as its own body.
  - Both checksums match only when the four lanes are in the order 12, 13, 19, 15. This confirms the lane order of the three members.
- **Host CPU.** The 2nd Boot entry at bank offset 0x1010 disassembles cleanly: `bsr` to a routine with `movec cacr,d0`, `cpusha dc`, `cinva ic`, then `movec d0,cacr` with 0x8000 and a `reset`/`jmp (a0)`. These are MC68040 (or 68060) instructions, which a CPU32 core such as the MC68360's would trap as line-F. The OS image `/nsx.sys` (first block on 15) starts the same way. Its CACR value is 0x80008000, or 0xB0E08000 when the byte at 0x471 is 0x3C (60). It also tests bit 23 and sets 0x600000, which are the 68060 branch-cache bits. It then programs a register block at 0x05001000 at +0x52, +0x62, +0x72 … in steps of 0x10, the layout of the MC68360's memory-controller base registers. The main CPU is therefore a 68040 or 68060, with the MC68360 QUICC(s) mapped at 0x05000000 as communication controllers (the 68360's "040 companion" arrangement).

## Device

**Seiko Instruments NS-2482 Multi Access Server**, system software Ver 3.1 (1998-08-31), last updated 1999-07-12 06:20 UTC. Confidence: **high**.

- The product and version come from `/version`, `/os_version`, the SNMP `SysDescr` text noted on 15 and 19, and the boot banners rebuilt above.
- All three chips belong to the same unit. The unit's file system is consistent across all three, down to block pointers, directory entries and byte-sum checksums.
- Chip 12's place in this unit is now also **high**: 64 positive cross-chip checks pass with no failure, against 34 failures for a chip 0 from another unit.
- The main processor is a 68040 or 68060 (confidence **medium**: two independent boot and OS routines, but no part name in the text). The MC68360 QUICCs are peripherals. The recorded `CPU: MC68360 QUICC` fact should be read in that light.

## Missing members

**Lane 1, chip 1 (D23–D16).**

How to recognise it:

- Every 64 KB sector starts `24 11 00 80 00 00 00 80 00 01 00 80 00 01 02 00 00 40 00 20`.
- The logical units at +0x24 are exactly 01 05 0D 19 1A 1E 21 22 26 2A 2F 33 36 3B 3E 45 47 4D 51 53 54 57 5B 5C 61 65 69 6D 71 75 79 7D. No unit is FFFF (spare).
- Sector 0 at 0x400 starts `42 F6 00 00 3C 00 7A 00` (identical to 5, 13 and 17).
- It shares no logical unit with 12, 19 or 15. Unlike 13 and 17, it should also not clash with them on unit content.
- Its never-rewritten units at sectors 0x18–0x1F should be 0x61 … 0x7D.

What it would add:

- The 1,090 referenced blocks that are still missing, which would complete 156 files. These include all of `/boot.3rd` (the 3rd-stage loader, 33 blocks plus its indirect block) and the remaining 246 of 304 blocks of the OS image `/nsx.sys`.
- The names of 16 inodes in `/admin`, `/driver` and `/sbin`.
- The unit's own lane 1 of the boot area, so the two boot checksums could be checked without borrowing from unit B.
- Logical unit 0x0D, the last block range of the inode table (inodes 2512–3019, probably empty).

## Open questions

- **A sixth unit.** Could chip 12 belong to a further, unseen unit whose allocation is identical to unit A's? Unit C's bitmap matches unit A's exactly, so allocation alone cannot exclude this. Only unit-specific content would. Next step: search 12 for site-specific configuration (for example `/tmp/setup` targets, `/save/setup/*` files) and compare with 15 and 19.
- **Header fields.** The `2BFR`/`HPOC` word 0x03F6 at +0x04, `HPOC` +0x08 (0x0007B700) and the FTL header word at +0x26 are not decoded. The xflush parameter longs 0x1D45–0x1FC0 and `C3 46 DF FF` at 12:0x0003FC are also open.
- **Deleted 2nd-boot copy.** Parts of the 2nd Boot code also appear in free blocks of logical unit 0x0E (19:0x160A00 onward, blocks 1782–1801). They may be an older `/boot.*` file deleted in an update. Rebuilding those blocks in order and comparing with bank offsets 0x1100–0x3A00 would show the version.
- **Host CPU.** 68040 or 68060, and which byte at 0x471/0x473 the POC sets. Next step: disassemble more of `/nsx.sys` and POC-IDL (bank offset 0x4130 onward) for a CPU-detection routine or PCR (68060) access.

## Method

Each chip's 32 sector headers were read, and their 127 data blocks were placed at logical block `unit × 127` to form an 8 MB image, with 0xAA for chip 1's units. The superblock, bitmaps and 128-byte inodes were parsed, and the directory tree was walked from inode 0, including indirect blocks. Each file's blocks were checked against the bitmap, the `ABCD` length field, end-of-file padding and unit B's copies (chips 3 and 13 rebuilt the same way). The same checks were repeated with chip 3 in place of 12 as a control. Sector 0 was interleaved at stride 4, from chip offset 0x400 to bank offset 0x1000, in lane order 12, (13), 19, 15. Header checksums were verified, and the entry code was disassembled with Capstone (68040 mode). All scripts were Python 3 with `-I`, run in a temporary directory, and the images were drawn with Pillow.
