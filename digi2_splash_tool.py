cat << 'EOF' > digi2_splash_tool.py
#!/usr/bin/env python3
"""
DigiSplash-II: Custom Boot Splash & Animation Patcher for Digitakt II (OS 1.17)
Standalone single-file toolchain.
"""

import argparse
import os
import subprocess
import sys
from PIL import Image, ImageSequence

VERSION = "2.2.0"
BASE_ADDR = 0x40000400

# Verified OS 1.17 Offsets
RNG_OFFSET = 0x1520B0
BURN_OFFSET = 0x0D1622
THRESHOLDS = [0x0D1626, 0x0D1632, 0x0D1646, 0x0D1668]
STATIC_ASSET_OFFSET = 0x307B18
ROM_CAVE_FRAMES = 0x2E0800
ROM_CAVE_TABLE = 0x2E2800
ROM_CAVE_PLAYER = 0x2E2840
SLOT3_OFFSET = 0x0D0DF0


def pack_frame(im, invert=False):
    """Encodes a 128x64 image into native SSD1306 column-major format."""
    im = im.convert("RGB").convert("1", dither=Image.Dither.NONE)
    if im.size != (128, 64):
        im = im.resize((128, 64), Image.Resampling.NEAREST)

    if invert:
        im = Image.eval(im, lambda p: 255 if p == 0 else 0)

    # Invert vertical axis for physical OLED panel orientation
    im = im.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    pix = im.load()

    # Column-major MSB-at-top
    col_bytes = bytearray(1024)
    idx = 0
    for col in range(128):
        for y_byte in range(8):
            byte = 0
            for bit in range(8):
                y = y_byte * 8 + bit
                if pix[col, y] > 128:
                    byte |= (0x80 >> bit)
            col_bytes[idx] = byte
            idx += 1
    return bytes(col_bytes)


def process_input(file_path, invert=False):
    """Loads input media and returns (is_animated, payload_bytes)."""
    im = Image.open(file_path)
    is_anim = getattr(im, "is_animated", False) and getattr(im, "n_frames", 1) > 1

    if not is_anim:
        return False, pack_frame(im, invert=invert)

    # Resample animated GIF to 8 evenly-spaced frames
    all_frames = [f.copy() for f in ImageSequence.Iterator(im)]
    total = len(all_frames)
    step = max(1, total // 8)
    selected = all_frames[::step][:8]
    while len(selected) < 8:
        selected.append(selected[-1])

    packed_frames = bytearray()
    for frame in selected:
        canvas = Image.new("RGBA", im.size, (0, 0, 0, 255))
        canvas.paste(frame)
        packed_frames.extend(pack_frame(canvas, invert=invert))

    return True, bytes(packed_frames)


def render_ascii_preview(frame_bytes):
    """Renders a terminal OLED preview from the hardware buffer."""
    lines = []
    for y in range(63, -1, -2):
        row = []
        for x in range(128):
            y_byte = y // 8
            bit = y % 8
            top = bool(frame_bytes[x * 8 + y_byte] & (0x80 >> bit))
            y2 = y - 1
            bot = bool(frame_bytes[x * 8 + (y2 // 8)] & (0x80 >> (y2 % 8))) if y2 >= 0 else False
            if top and bot: row.append("█")
            elif top: row.append("▀")
            elif bot: row.append("▄")
            else: row.append(" ")
        lines.append("".join(row))
    return "\n".join(lines)


def apply_patches(rom, is_anim, payload_bytes, mode="equal"):
    """Applies entropy, thresholds, assets, and player code."""
    # 1. Entropy & first-draw burn
    rom[RNG_OFFSET:RNG_OFFSET+6] = bytes.fromhex("D0B9FC07000C")
    rom[BURN_OFFSET:BURN_OFFSET+2] = bytes.fromhex("4E93")

    # 2. Probability Thresholds
    if mode == "100percent":
        rom[THRESHOLDS[0]:THRESHOLDS[0]+4] = bytes.fromhex("00000000")
        rom[THRESHOLDS[1]:THRESHOLDS[1]+4] = bytes.fromhex("00000000")
        rom[THRESHOLDS[2]:THRESHOLDS[2]+4] = bytes.fromhex("00007FFF")
        rom[THRESHOLDS[3]:THRESHOLDS[3]+4] = bytes.fromhex("00000000")
    else:  # 'equal' (25% each across A, B, C, D; Variant E disabled)
        rom[THRESHOLDS[0]:THRESHOLDS[0]+4] = bytes.fromhex("00001FFF")
        rom[THRESHOLDS[1]:THRESHOLDS[1]+4] = bytes.fromhex("00002AAA")
        rom[THRESHOLDS[2]:THRESHOLDS[2]+4] = bytes.fromhex("00003FFF")
        rom[THRESHOLDS[3]:THRESHOLDS[3]+4] = bytes.fromhex("00007FFF")

    if not is_anim:
        # Static asset replacement
        rom[STATIC_ASSET_OFFSET : STATIC_ASSET_OFFSET + 1024] = payload_bytes
    else:
        # Animated Engine
        # A. Frames in ROM Cave
        frames_rt = ROM_CAVE_FRAMES + BASE_ADDR
        rom[ROM_CAVE_FRAMES : ROM_CAVE_FRAMES + 8192] = payload_bytes
        rom[STATIC_ASSET_OFFSET : STATIC_ASSET_OFFSET + 1024] = payload_bytes[:1024]

        # B. 48-byte Lookup Table (6 ticks per frame @ 10 fps)
        table_rt = ROM_CAVE_TABLE + BASE_ADDR
        table = bytearray()
        for idx in range(8):
            table.extend([idx] * 6)
        rom[ROM_CAVE_TABLE : ROM_CAVE_TABLE + 48] = table

        # C. Straight-line ColdFire Player Routine
        player_rt = ROM_CAVE_PLAYER + BASE_ADDR
        p = bytearray()
        p.extend(b"\x20\x39\x44\xF3\x6D\x3C")               # move.l 0x44F36D3C, %d0
        p.extend(b"\x52\x80")                               # addq.l #1, %d0
        p.extend(b"\x0C\x80\x00\x00\x00\x30")               # cmpi.l #48, %d0
        p.extend(b"\x65\x02")                               # bcs.s +2
        p.extend(b"\x42\x80")                               # clr.l %d0
        p.extend(b"\x23\xC0\x44\xF3\x6D\x3C")               # move.l %d0, 0x44F36D3C
        p.extend(b"\x41\xF9" + table_rt.to_bytes(4, "big")) # lea table_rt, %a0
        p.extend(b"\x72\x00")                               # moveq #0, %d1
        p.extend(b"\x12\x30\x08\x00")                       # move.b (0, %a0, %d0.l), %d1
        p.extend(b"\xE1\x81\xE5\x81")                       # lsl.l #8, %d1; lsl.l #2, %d1 (* 1024)
        p.extend(b"\x06\x81" + frames_rt.to_bytes(4, "big"))# addi.l #frames_rt, %d1
        p.extend(b"\x23\xC1\x44\xF3\x6D\x34")               # move.l %d1, 0x44F36D34 (PIXELS!)
        p.extend(b"\x42\xA7\x42\xA7\x42\xA7")               # 3x clr.l -(%sp)
        p.extend(b"\x48\x79\x44\xF3\x6D\x24")               # pea 0x44F36D24
        p.extend(b"\x2F\x2F\x00\x1C")                       # move.l 0x1C(%sp), -(%sp)
        p.extend(b"\x4E\xB9\x40\x11\x41\x68")               # jsr 0x40114168
        p.extend(b"\x4F\xEF\x00\x14")                       # lea 0x14(%sp), %sp
        p.extend(b"\x4E\x75")                               # rts
        rom[ROM_CAVE_PLAYER : ROM_CAVE_PLAYER + len(p)] = p

        # D. 6-byte Trampoline in Slot 3
        trampoline = bytearray(b"\x4E\xF9" + player_rt.to_bytes(4, "big"))
        while len(trampoline) < 28:
            trampoline.extend(b"\x4E\x71")
        rom[SLOT3_OFFSET : SLOT3_OFFSET + 28] = trampoline

    return rom


def main():
    parser = argparse.ArgumentParser(description="Digitakt II Splash & Animation Tool")
    parser.add_argument("-i", "--input", default="Digitakt_II_OS1.17.syx", help="Official OS SysEx")
    parser.add_argument("-o", "--output", default="Digitakt_II_OS1.17_custom.syx", help="Output SysEx")
    parser.add_argument("-m", "--media", required=True, help="Input file (PNG/JPG/GIF)")
    parser.add_argument("--mode", choices=["equal", "100percent"], default="equal", help="Probability mode (default: equal 25%%)")
    parser.add_argument("--invert", action="store_true", help="Invert colors")
    parser.add_argument("--preview", action="store_true", help="Show terminal preview and exit")
    parser.add_argument("-f", "--flash", action="store_true", help="Automatically flash output via amidi")
    parser.add_argument("-p", "--port", default="hw:1,0,0", help="ALSA MIDI port (default: hw:1,0,0)")

    args = parser.parse_args()
    tool = "./elektron-firmware-tool/elektron-firmware-tool"

    if not args.preview and not os.path.exists(tool):
        sys.exit(f"Missing {tool}. Build it: (cd elektron-firmware-tool && make)")

    print(f"=== DigiSplash-II v{VERSION} ===")
    is_anim, payload = process_input(args.media, invert=args.invert)
    print(f"Media Type: {'8-Frame Animation' if is_anim else 'Static 128x64 Image'}")

    preview_frame = payload[:1024] if is_anim else payload
    print("\nTerminal OLED Preview (Frame 0):")
    print("-" * 64)
    print(render_ascii_preview(preview_frame))
    print("-" * 64)

    if args.preview:
        print("Preview mode active. Exiting without modifying firmware.")
        return

    # Decompress Section 3 directly from the input SysEx file using elektron-firmware-tool
    section3_file = "section_3_MAIN_OS.bin"
    if not os.path.exists(section3_file):
        print(f"Decompressing Section 3 from {args.input}...")
        subprocess.run([tool, "-i", args.input, "-d", "3", "-o", "."], check=True)

    with open(section3_file, "rb") as f:
        rom = bytearray(f.read())

    patched = apply_patches(rom, is_anim, payload, mode=args.mode)
    patched_file = "section3_patched.bin"
    with open(patched_file, "wb") as f:
        f.write(patched)

    print("\nRebuilding flashable SysEx...")
    subprocess.run([tool, "-i", args.input, "-c", "3", patched_file, "-o", args.output], check=True)
    subprocess.run([tool, "-i", args.output], check=True)
    print(f"\nSUCCESS: Output written to {args.output}")

    if args.flash:
        print(f"\nFlashing directly to Digitakt II on port {args.port}...")
        subprocess.run(["amidi", "-p", args.port, "-s", args.output], check=True)
        print("Flash complete! Digitakt II should be rebooting now.")
    else:
        print(f"Flash manually with: amidi -p {args.port} -s {args.output}")


if __name__ == "__main__":
    main()
EOF

chmod +x digi2_splash_tool.py
