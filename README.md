# DigiSplash-II
Custom Boot Splash & Animation Tool for Elektron Digitakt II (OS 1.17)

<img width="1303" height="903" alt="image" src="https://github.com/user-attachments/assets/2828ab11-675f-446f-b8ed-6fede233f186" />

DigiSplash-II is a standalone utility that allows you to inject custom static logos or full-motion animated boot sequences into the Elektron Digitakt II firmware.

It takes any standard image (PNG, JPG, BMP) or animated GIF, encodes it into the Digitakt II native SSD1306 OLED hardware format, and compiles a flashable .syx firmware update.
Features

    Any Image or GIF: Supports static artwork and multi-frame animations.

    Native Hardware Encoding: Encodes into SSD1306 Column-Major format (MSB-at-top, inverted Y).

    Zero Audio Popping: Disables the procedural Dither screen (Variant E) to eliminate boot noise.

    ROM-Safe Injection: Uses the 11.4 KB dead ROM cave at 0x2E0800. Does not touch audio DMA memory.

    Crash-Proof Player: Uses a 6-byte trampoline jump and a straight-line ColdFire player routine.

    One-Command Flashing: Automatic USB MIDI flashing via amidi.

Requirements

    Firmware: Official Digitakt II OS 1.17 (Digitakt_II_OS1.17.syx).

    OS: Linux (Fedora, Ubuntu, Arch, etc.) or macOS.

    Dependencies: Python 3.9+ with Pillow, gcc, make, alsa-utils.

Quickstart

    Clone and build the firmware container tool:
    git clone https://github.com/mischa85/elektron-firmware-tool.git
    (cd elektron-firmware-tool && make)

    Install Python image dependencies:
    pip install -r requirements.txt

    Place official Digitakt_II_OS1.17.syx in this directory.

Usage Examples

    Preview in terminal (no flashing):
    ./digi2_splash_tool.py -m my_logo.png --preview

    Inject animation (100% chance on boot):
    ./digi2_splash_tool.py -m my_anim.gif --mode 100percent -o My_Custom_DT2.syx

    Build and flash directly to Digitakt II over USB:
    ./digi2_splash_tool.py -m my_anim.gif --mode 100percent --flash

    Balanced 25% Easter egg rotation (A, B, C, D):
    ./digi2_splash_tool.py -m my_anim.gif --mode equal -o My_Custom_DT2.syx

Manual Flashing

    On Digitakt II: Press [SETTINGS] -> SYSTEM -> OS UPGRADE.

    From terminal:
    amidi -p hw:1,0,0 -s My_Custom_DT2.syx

Image Design Guidelines

    Resolution: Exactly 128 pixels wide x 64 pixels tall.

    Color Depth: 1-bit monochrome (#000000 is off, #FFFFFF is on).

    Animations: 8 frames running at ~10 fps (100 ms per frame) loop smoothly 3-4 times on boot.

Safety & Recovery

    Modifying the boot splash operates solely on Section 3 (Main OS) and cannot overwrite the hardware bootloader.

    If a corrupted OS is ever flashed, the unit will halt cleanly into an Exception screen (V04).

    Recovery: Power off, hold [FUNC] while powering on, press [TRIG 4] (OS Upgrade), and send any stock .syx firmware file over a 5-pin MIDI DIN cable.

Credits

    DigiAlchemy / mischa85: Authors of elektron-firmware-tool.

    Pierre Baillet (octplane): Author of the original Easter egg research (digitakt-ii-splash-screens).

    Atlin: Hardware validation, reverse engineering, and display layout testing.
    
