***

# Digitakt II Boot Architecture & Splash Reverse Engineering
**Target OS:** 1.17 (`Digitakt_II_OS1.17.syx`)  
**Architecture:** NXP ColdFire MCF54415 (Motorola 68000 ISA subset)  
**Base Address:** `0x40000400` (Section 3 / Main OS)

This document details the discoveries made while porting custom boot animations to the Digitakt II. It builds heavily on the foundational work by Pierre Baillet (`octplane`) and `DigiAlchemydsp`.

---

## 1. The Boot Sequence

The Digitakt II firmware is containerized. The sequence of execution on a cold boot is:

1. **Bootloader (`section2_unpacked.bin`):** Loads into on-chip SRAM at `0x02010000`. 
   * Checks if `[FUNC]` is held. If yes, it launches the **Early Startup Menu** (`TEST MODE`, `OS UPGRADE`).
   * *Note:* The Early Startup Menu **disables class-compliant USB MIDI**. To flash firmware from this menu, you *must* use the physical 5-pin MIDI DIN port.
2. **Decompression:** `section2` decompresses `section3` (the 3.2MB Main OS) from flash into DDR2 SDRAM.
3. **Stage 1 (Pre-Splash Banner):** `section3` begins execution at `0x40000400`. It initializes the OLED, draws the static Elektron badge, stamps the OS version (`1.17`), and pauses for ~1 second.
4. **Stage 2 (Splash Selector):** The OS clears the screen and executes the randomized splash routine at `0x400D1A12`.
5. **Stage 3:** The audio DMA buffers are initialized, and the main sequencer UI loads.

---

## 2. Display Hardware & Framebuffer Format

If you inject standard horizontal scanlines (like a desktop bitmap) into the Digitakt II, the image will render as shredded horizontal bands of vertical stripes.

The Digitakt II OLED (likely an SSD1306/SH1106 variant) is configured in **Column-Major Page Addressing Mode**, and the physical ribbon cable is mounted inverted.

**To perfectly map a 128×64 image to the hardware:**
1. **Invert the Y-Axis** (Flip Top-to-Bottom).
2. **Column-Major Encoding:** The framebuffer is exactly 1,024 bytes. It is read as 128 columns, with 8 vertical bytes per column.
3. **MSB at Top:** Within each byte, Bit 7 (`0x80`) is the top pixel, and Bit 0 (`0x01`) is the bottom pixel.

*Python reference for the exact hardware packing:*
```python
col_bytes = bytearray(1024)
idx = 0
for col in range(128):
    for y_byte in range(8):
        byte = 0
        for bit in range(8):
            y = y_byte * 8 + bit
            if pixels[col, y] > 128:  # If pixel is ON
                byte |= (0x80 >> bit) # MSB first
        col_bytes[idx] = byte
        idx += 1
```

---

## 3. The Graphic Blitter (`draw_bitmap`)

Every UI element and boot screen on the Digitakt II is drawn via a single master blit function located at `0x40114168` (file `0x113D68`).

It takes a pointer to a 20-byte C-struct in RAM. 
Example struct at `0x44F36D24`:
* `+0x00`: Header / Flags
* `+0x04`: Width (e.g., 128)
* `+0x08`: Height (e.g., 64)
* **`+0x0C`: Pixel Data Pointer** (Points to the actual 1-bit graphic in ROM)
* **`+0x10`: Mask Data Pointer**

To animate a graphic, your assembly routine only needs to calculate the new frame's memory address, write it to `[Struct Address] + 0x0C`, and call `jsr 0x40114168`. The 60 Hz OS refresh loop handles the rest.

---

## 4. Memory Layout & "Safe" ROM Caves

Finding safe space for custom animation frames is highly dangerous because the firmware is packed tight. 

**🚨 DANGER ZONES:**
* **`0x2E0800` (Global Font Sheet):** Do not overwrite this! Overwriting this space corrupts the Compressor "SCF" text, the USB Config menu, and other UI parameter text.
* **`0x3113D0`+ (Kernel BSS / Audio DMA):** The zero-padding at the end of the binary is active RAM for the audio engine. Writing graphics here will cause the DAC to play your pixel data as a loud, screeching noise burst on boot.

**✅ SAFE ZONE (Dedicated 8 KB Splash Buffer):**
The factory "Boombox" animation (Variant B) uses 8 contiguous full-screen frame buffers located between file offset **`0x30339C`** and **`0x30539C`**.
* This is exactly **8,192 bytes** (8 full 128×64 frames).
* It is 100% disconnected from the UI fonts and audio engine.
* You can safely overwrite this entire block with your own custom animation frames.

---

## 5. ColdFire Architecture Quirks & The "V04" Crash

The MCF54415 processor is a RISC subset of the classic Motorola 68000. 
If you attempt to use legacy 68k instructions (like `divs.w`), the Digitakt II will immediately halt into a blue **`EXCEPTION DS0082 / V04`** (Illegal Instruction) screen.

**The Trampoline Architecture:**
The factory slots are very short (e.g., Slot 3 is only 28 bytes long). Trying to fit a full animation loop here will overflow into Slot 2 and crash the OS.
Instead, use a **6-byte trampoline jump**:
```assembly
jmp 0x402E2C40  ; 4E F9 40 2E 2C 40
nop             ; 4E 71 (Pad remainder of the 28-byte slot)
```

**Table-Driven Logic (Zero Branches):**
Relative branches (`bsr`, `bra`) in hand-assembled hex are risky. An off-by-2 byte error will cause the CPU to jump into an immediate constant, triggering a `V04` exception. 
The safest way to animate is a **straight-line, table-driven player**:
1. Read the live OS tick counter (`0x44F36D3C`).
2. Use the tick to index a 48-byte precomputed frame-lookup table in ROM.
3. Multiply the result by 1,024 (`lsl.l #8`, `lsl.l #2`).
4. Add the base address of your 8KB frame buffer.
5. Update the struct and blit.

---

## 6. The Variant E "Audio Pop" Bug

In the stock OS 1.17 firmware, the "Dither" screen (Variant E) calculates a procedural noise pattern dynamically in RAM (`0x4314D5D8` to `0x431535D8`). 
* Because Elektron never seeded the RNG, Variant E essentially *never ran* on factory machines.
* Once the RNG is patched via the DMA Timer (DTIM0), Variant E becomes active.
* **The Bug:** Variant E's 24 KB scratchpad overlaps with the audio DMA ring buffers. When it executes, it fills the audio buffers with visual static. When the main OS boots, the DAC unmutes and plays this static as a loud pop/screech.

**The Fix:** Disable Variant E entirely by setting Threshold 4 (`0x0D1668`) to `0x00007FFF`. This distributes the probabilities evenly (25% each) across Variants A, B, C, and D, resulting in a dead-silent, completely stable boot process.

---
*Documented October 2026 by Atlin & Community.*
