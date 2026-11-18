---
title: SH car navigation firmware pair
summary: Two MBM29F016A chips that interleave into the complete 4 MB SH-2 (SH7040-series) application firmware of a Toyota dealer-option car navigation unit with a CD-ROM map drive, VICS and MONET support, built 25 September 1997.
status: done
tags: [16-bit, big-endian, superh, sh7040, car-navigation]
updated: 2026-11-18
model: claude-opus-5-5
members: [MBM29F016A/18, MBM29F016A/7]
---

MBM29F016A/18 (even bytes, D15-D8) and MBM29F016A/7 (odd bytes, D7-D0) are the two byte lanes of one 16-bit flash bank. Interleaved, they give a complete, self-consistent 4 MB big-endian SuperH program linked at 0x00800000 (chip select area CS2), with nothing missing. Code disassembles cleanly throughout. 69 RCS `$Header$` strings become fully readable, for example `$Header: cd.c,v 1.2 96/03/28 03:14:12 ariizumi cdctrl $`. So do about 40 KB of Japanese Shift-JIS menu text and a build stamp of `Sep 25 1997:20:18:05`. The text names the product's world. It tells the user to ask a **Toyota dealer** (トヨタ販売店) about map CD-ROM updates, offers a key to go back to the **MONET** screen (Toyota's telematics service, introduced 1997-98), and covers VICS and FM-multiplex traffic data, a multi-CD changer, MD and tape sources, a TV tuner, voice control, PC cards, and program updates loaded from the map disc. A source file named `avndop_map_sysrom.c` uses Toyota's own term for dealer-option ("DOP") audio-visual navigation ("AVN"). On-chip register addresses and interrupt vector numbers identify the CPU as a Hitachi SH7040-series SH-2.

## Layout

| Bank | Lane | Data bits | Dump | CPU addresses |
|---|---|---|---|---|
| 0 | 0 | D15-D8 | MBM29F016A/18 | 0x00800000 + 2n |
| 0 | 1 | D7-D0 | MBM29F016A/7 | 0x00800000 + 2n + 1 |

Byte n of each chip is word n of the bus. Offset X on the rebuilt bus is CPU address 0x00800000 + X, and it holds bytes 18:X/2 and 7:X/2. Both chips are 2 MB, so the bank fills the 4 MB of CS2 (0x00800000-0x00BFFFFF) exactly. Both chips have content up to chip offset 0x1F3F49 and are erased after it, apart from a shared trailer at 0x1FFFE8.

The lanes before and after interleaving, at chip offset 0x01003C (bank offset 0x020078). The first two lines show each lane in its place on the bus, with `·` marking bytes held by the other chip:

```
18:  $·e·d·r· ·d·c·v·1·2·9·/·3·2· ·3·1·:·2·a·i·z·m· ·d·t·l·$·
 7:  ·H·a·e·:·c·.·,· ·.· ·6·0·/·8·0·:·4·1· ·r·i·u·i·c·c·r· ·
bus: $Header: cd.c,v 1.2 96/03/28 03:14:12 ariizumi cdctrl $
```

| Bank offset | Contents |
|---|---|
| 0x000000 | Image header: `AA`×16, magic `12345678` at 0x10, parameters, `AAAAAAAA BBBBBBBB CCCCCCCC DDDDDDDD` markers at 0x30 and 0x64 |
| 0x000074 | 256-entry exception vector table (VBR = 0x00800074) |
| 0x000474 | Small configuration tables and a handler table (0x4E0) |
| 0x000538 | Task table, 67 × 16 bytes |
| 0x0015C8 | 252 default exception stubs `bra 0x008019B8 / mov #n,r4` |
| 0x000C4C-0x342850 | Main program: about 3.3 MB of SH code with literal pools, plus a few inline tables |
| 0x342850-0x3E38B0 | Constant data: pointer tables, POI and menu tables, Japanese UI strings, FM/TV station tables |
| 0x3E38B0-0x3E7E93 | Tail code block: software floating-point and math library, ending with `avn_map_dram.c` |
| 0x3E7E94-0x3FFFCF | Erased (FFh) |
| 0x3FFFD0 | Trailer `00000000 2D2D2D2D 2D2D2D2D 007C8271` twice, then `AA`×16 |

![Rebuilt image map](images/rebuilt-image-map.png)

## Findings

- **The interleave is right.** Vector entries read as `0x008015C8 + 4(n-4)` and each one lands on its own stub. The stubs at bank offset 0x15C8 decode as `a1f6 e404`, `a1f4 e405` … (`bra 0x008019B8` / `mov #4,r4`, and so on), and the common handler at 0x008019B8 is `mov.l @(…),r0 / jmp @r0 / extu.b r4,r4`, which jumps to 0x00480864. Pointers to strings land on those strings. For example, the pointers to `APC`, `LBC`, `SND`, `RCV` at bank offset 0x14B718 hold 0x00B6B114-0x00B6B120, which is bank offset 0x36B114, where the four names sit. This confirms both the lane order and the 0x00800000 link base.
- **Header (bank offset 0x000000).** The full words are: `AAAAAAAA`×4, `12345678`, `0A000100`, `8B000000`, `0310FFFF`, `00000030`, `00FFFFA0`, `00FFFFD0`, `00000000`, then the four markers. These are followed by `00B42850 97ABC60F 000002A0 D67D6E6D 000010F0 D23BF1E6 000006EA 7B991915 00000C78` and the markers again at 0x64. The first value, 0x00B42850, is exactly the CPU address where the main code ends and constant data begins (bank offset 0x342850). The alternating values look like (size or address, check value) pairs. I tested byte, 16-bit and 32-bit sums and CRC-32 over every range starting at 0, 0x10, 0x40, 0x64, 0x74 or 0x342850, and none produces the check values or the trailer's `007C8271`. The check algorithm is still unknown.
- **Vector table (bank offset 0x74).** Vectors 0-3 read `00000400 00000000 00000400 00000000`. So the image names power-on and manual reset PC = 0x00000400 in area 0, but this table is only used through VBR. TRAPA #60-63 go to area 0 at 0x000030A4, 0x00002F00, 0x00000DA4 and 0x00000E4C. These are the "A4/4C" addresses the lane analyses predicted. NMI (vector 11) goes to 0x008021B0; MBM29F016A/7's write-up guessed 0x008015B0 because its high byte was missing. Dedicated handlers are installed for vectors 64, 66, 68-71, 76, 84, 112-114, 120-123, 128-129, 132-135, 144 and 148. In the SH7040-series numbering these are IRQ0/2/4-7, DMAC1 and DMAC3, MTU channels 3 and 4, SCI0 receive, all of SCI1, and CMT0/CMT1. The SH7032/7034 has no interrupt vectors above 113, so those parts are ruled out.
- **On-chip registers confirm the SH7040 series.** Sign-extended `mov.w` literals address 0xFFFF81A0-81A5 and 0xFFFF81B0-81B5 (SCI0/SCI1, about 120 uses), 0xFFFF8200-82BC (MTU), 0xFFFF8348-8358 (INTC IPRA-IPRH and ICR), 0xFFFF8380-83B8 (PFC and I/O ports), 0xFFFF83D0-83DC (CMT) and 0xFFFF86B0-86FC (DMAC). This is the SH7040/7041/7042/7043/7044/7045 register map. The code itself is SH-1 code: `mul.l` is followed by `sts macl` only twice, against 2,575 `mulu.w`/`muls.w` pairs. So the compiler most likely targeted the SH-1 instruction set, which the SH-2 also runs.
- **System memory map, from about 30,000 call targets and 100,000 literal references in the rebuilt code.** 21,675 calls stay inside this image. 2,904 calls go to area 0 at 0x0000_0DA4-0x0003_E568 (the routine at 0x000066AC alone is called 1,360 times, so area 0 holds a shared runtime library). 5,809 calls go to CS1, almost all to 0x005F5000-0x005FBFFF, with 8,895 data references to the same block. A further 14 kernel-style entry wrappers lead to 0x00480808-0x00480AFC, which has 2,025 data references (the common interrupt handler enters at 0x00480864). DRAM at 0x01200000-0x015DFFFF takes about 68,000 data references, and CS0 at 0x00200000-0x0021FFFF takes 2,100 (byte I/O registers, for example a write to 0x00200607 at 0x008216F6). Every area-0 target lies below 0x40000. That fits the 256 KB on-chip ROM of an SH7044 or SH7045 in single-chip-ROM mode, but an external boot ROM of at least 256 KB would fit too.
- **Task table (bank offset 0x538).** It holds 67 records of `{u16 id; u16 attr; u32 entry; u16 priority; u16 ?; u32 stack}`. For example, id 2 is entry 0x008BC3B8, priority 11, stack 0x500, and id 4 is entry 0x00034E7C (area 0), priority 25, stack 0x3C00. Priorities run from 1 to 40 and stacks from 0x100 to 0x3C00 bytes. Ids 9, 29, 32, 39, 40, 47 and 48 have no entry. Tasks 4 and 60 start in area 0 and task 67 in the late part of the program (0x00B10A78). This looks like a static task-creation table for an ITRON-style real-time kernel. The single-lane analysis of MBM29F016A/7 could see only bytes 1 and 3 of these fields.
- **Source files (69 RCS headers, 1996-03-05 to 1997-09-09).** By author: ariizumi 29 (`cd.c`, `cd_fri_*.c`, `reference.c`, and 21 `diag_*.c` files including `diag_gps.c`, `diag_gmem.c`, `diag_spd.c` and `diag_rot.c`), nakata 21 (the `chg_`, `mchg_`, `nchg_` and `schg_` screen-change task modules, plus `sh_debug.c`), utena 6 (`ini_adpcm.c`, `ini_voice.c`, `ini_vupinf_mrom.c`, `ini_zuyo.c`), alcyone 4 (`avndop_map_sysrom.c`, `avn_map_dram.c`, `pal_calc.c`, `chg_locu.c`), mciisobe 3 (`procinf1-3.c`), takagi 2, nakano 2, mcigam 1 (`proc8220.c`) and lisyos 1 (`atapitbl.c`, 97/08/01). The CD-ROM drive is reached through ATAPI. Bank offset 0x025700 holds the command-table names `TRACK NO=0`, `A_BIOS_DmyToc`, `A_BIOS_DmyPlay`, `A_SetFeatureP1` and others.
- **Build stamps.** `Sep 25 1997:20:18:05` (a C `__DATE__`/`__TIME__` pair) follows the `APC`/`LBC`/`SND`/`RCV` names at bank offset 0x36B120. `J-NAVI youhin2  version 01.00-00  date 95.04.03 time 00:00` at bank offset 0x3C55E8 looks like an embedded version record for an older component. *youhin* (用品) is Toyota's word for accessories, but the meaning of `J-NAVI` here is unconfirmed.
- **Japanese UI text (bank offset 0x393644-0x396400, plus tables at 0x06B088, 0x096B53 and 0x36ABA0).** Destination, waypoint, route, track and memory-point editing; *trip track 1-5*; arrival-time and average-speed settings; a 50-sound kana and JIS level-1/2 kanji name input; and phone-number search. The map credit (0x3953BC) says the CD-ROM maps come from the Japan Digital Road Map Association database, and that updates are handled by Toyota dealers (0x39541A). The "new features" page (0x3954C4) lists routing via up to five waypoints, version-up capability, highway mode and simulation mode. The supported options are the VICS system, multi-CD changer, voice operation system and a PC card. Messages also cover VICS/FM-multiplex text and graphic information, the MONET screen (0x39432E), the TV tuner, MD and tape errors, and a self-test menu (`ダイアグメモリ`, `スイッチ検査`, `システム検査`, `ＤＰ検査メニュー` at 0x3936C6-0x39395C). Alert sounds for memory points include a nightingale, galloping horses, applause and a music box (0x0979D0). The POI category tables at 0x06D704 and 0x072286 include `トヨタ販` (Toyota dealer) and `トヨタレ` (Toyota rent-a-car).
- **Broadcast tables (0x3CC49E-0x3E38B0).** These hold Japanese FM stations (`クロスＦＭ`, `ＦＭとやま`, `ＦＭヨコハマ`), AM stations (`ニッポン放送`, `東海ラジオ`, `ラジオ沖縄`) and a nationwide list of TV stations from `札幌テレビ` to `沖縄テレビ`. They support FM-multiplex (VICS) station selection and the TV tuner.
- **Program update from the map disc.** The strings at 0x394968-0x394A1E say "Rewriting the program", "Do not switch off or remove the disc", "A map disc containing a new program is loaded" and "Will rewrite the navigation program". That explains why the firmware is in flash and why the image carries a header and trailer with check values. No AMD-style flash command sequences (0x5555/0xAAAA to the CS2 window) appear in this image. The writer is therefore probably in area 0 and reached through the TRAPA services.
- **Tail code block (0x3E38B0-0x3E7E93).** The functions pass 12-byte floating-point values on the stack (`mov #12,r0; sub r0,r15`). They use constants with 96-bit extended-precision mantissas: `C90FDAA2 2168C235` is pi and `B17217F7 D1CF79AC` is ln 2 (at 0x3E7E10-0x3E7E44). They also call the CS1 library at 0x005F6764 and 0x005F9194. This is a software floating-point and transcendental library, probably for map projection and dead reckoning.

![UI text sample](images/ui-text-sample.png)

## Device

**A Toyota dealer-option ("DOP") CD-ROM car navigation unit for the Japanese market, built in September 1997.** Confidence: **high** that it is a Toyota-channel CD-ROM navigation with GPS, VICS/FM-multiplex and MONET support; **medium** that it is a dealer-option rather than a factory-fitted unit; **low** for the actual manufacturer and model number.

The evidence for the product class is all in the rebuilt image. It has GPS, speed-pulse and gyro diagnostics, an ATAPI CD-ROM map drive, VICS and FM-multiplex screens, and a pointer back to the MONET service. Map updates are routed to Toyota dealers, and the POI categories include Toyota dealers and rental shops. The file name `avndop_map_sysrom.c` matches Toyota's own "DOP AVN" (dealer-option audio-visual-navigation) term, which Toyota still uses in its accessory web paths. The tape, MD, multi-CD changer and TV tuner messages show an integrated audio-visual navigation head unit, not a navigation-only box.

The CPU is a Hitachi SH7040-series SH-2, probably an SH7044 or SH7045 if area 0 is on-chip ROM.

The manufacturer is not named anywhere in the image. Toyota dealer-option navigation of this period came from several suppliers. "AVN" is also Fujitsu Ten's (Eclipse) product term, and three login names begin with `mci` (`mciisobe`, `mcigam`), which could stand for a subcontractor such as Matsushita Communication Industrial. Neither clue is strong enough to name a maker.

## Missing members

The bank itself is complete: both lanes are present, and no data is lost. The rest of the system's memory is not in this group.

- **Area 0, 0x00000000-0x0003FFFF (boot ROM or MCU on-chip ROM).** This would give reset code at 0x00000400, the TRAPA #60-63 handlers at 0x000030A4, 0x00002F00, 0x00000DA4 and 0x00000E4C, the runtime routine at 0x000066AC, tasks 4 (0x00034E7C) and 60 (0x00037EA8), and probably the header check and flash writer. How to recognise it: big-endian SH code of up to 256 KB with a reset vector of 0x00000400, `ldc rN,vbr` of 0x00800074, and literals `12345678`, `AAAAAAAA` to `DDDDDDDD` and 0x00800000. If the CPU is an SH7044F/SH7045F, this is the MCU's internal flash, not a separate chip.
- **CS1, 0x00400000-0x007FFFFF.** It holds a kernel-like block at 0x00480800-0x00480B00 (entered from every exception stub) and a library at 0x005F5000-0x005FBFFF that the program calls 5,800 times. This may be ROM (perhaps the "sysrom" of `avndop_map_sysrom.c`, possibly with the kanji fonts the navigation display needs, which are absent from this image) or RAM loaded at boot. How to recognise it: SH code at device offset 0x080808 (if the device is based at 0x00400000) and at 0x1F5600-0x1FAD00, with function entries at 0x1F5600, 0x1F5828, 0x1F60E4 and 0x1F6C78.
- **Area 0 or CS0 peripherals** (0x00200000-0x0021FFFF) are byte-wide I/O such as the graphics controller, CD-ROM interface and audio bus, not memory to dump.

## Open questions

- **Header and trailer check values.** What algorithm produces `97ABC60F`, `D67D6E6D`, `D23BF1E6`, `7B991915` and the trailer `007C8271`? The next step is to disassemble the callers of the `12345678`/`AAAAAAAA` constants once the area-0 code is available, or to try CRC-16/CRC-32 variants and word sums per lane over the code and data sections that the header sizes 0x2A0, 0x10F0, 0x6EA and 0xC78 might describe.
- **Exact maker and model.** Search a second-hand-parts or service context for Toyota 1997-98 dealer-option navigation with MONET support (for example the `08545-` accessory part-number family), and compare its stickers or manual with the UI wording here (`ＤＰ検査メニュー`, alert sounds `ウグイス` and `馬の走る音`).
- **What `J-NAVI youhin2` (bank offset 0x3C55E8) and the `APC`/`LBC`/`SND`/`RCV` module names stand for.**
- **CS1 contents.** Determine from code that writes into CS1 whether the 0x005F5000 library is copied to RAM at boot (look for block copies whose destination is 0x00400000-0x007FFFFF) or executes from a ROM.

## Method

I interleaved the two chips in Python (`python3 -I`), with 18 on the even bytes and 7 on the odd bytes, to make a 4 MB image based at 0x00800000. I checked the result with a small hand-written SH disassembler: the vector stubs, the common handler, prologues and epilogues, and string pointers all landed correctly. The RCS headers, ASCII strings and Shift-JIS runs were extracted from the rebuilt image. Statistics came from PC-relative `mov.l`/`mov.w` literals: calls (literal followed by `jsr`), data references by address area, and sign-extended 16-bit peripheral addresses. I decoded the task table and the vector table as 32-bit big-endian structures, and tested header check values with prefix sums (8, 16 and 32-bit) and CRC-32. The block map classifies 4 KB blocks by SH idiom density (`rts`, `sts.l pr`, `jsr`), Shift-JIS density, and zero and FFh fill.
