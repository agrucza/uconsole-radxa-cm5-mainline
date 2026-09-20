#!/usr/bin/env python3
"""Find out whether the AIO v2 SX1262's MISO reaches ANY GPIO on the Radxa CM5.

Background (docs/aio-v2.md, "LoRa: no path as wired"): the AIO's MISO line arrives at
module connector position 26, which Radxa documents as not connected. Documentation
was wrong once before on this board (the RTC), so this script tests the module itself.

Method: bit-bang SX1262 GetStatus transactions on the known CLK/MOSI/CS lines. The
chip answers every byte with its status byte on MISO, a fixed pattern of 0s and 1s.
At every clock edge the script samples every free GPIO line on all Rockchip
gpiochips. A line that reproduces the same non-constant 16-bit pattern on every
repeat while CS is low, and does not while CS is high, is MISO arriving somewhere.

Safety:
  - Only lines that are UNCLAIMED in the pinctrl pinmux table AND unused by any
    kernel consumer are sampled, so no peripheral (UART, I2C, SPI, eMMC, USB, ...)
    is re-muxed or disturbed. The check needs debugfs; the script mounts it if
    necessary and refuses to run without it.
  - Nothing is driven except the SX1262's own CLK, MOSI, CS and Reset lines, the
    same ones tools/sx1262-bitbang.py already drives.

Run as root with the LoRa rail on:   sudo aio lora on && sudo ./lora-miso-scan.py
Needs the libgpiod v2 Python bindings (python3-libgpiod).
"""
import glob
import os
import re
import subprocess
import sys
import time

import gpiod
from gpiod.line import Direction, Value

# SX1262 lines on gpiochip1 (see docs/gpio-map.md, "Expansion slot routing")
CHIP1 = "/dev/gpiochip1"
MOSI, CLK, CS, BUSY, RST, RAIL, MISO_SOC = 1, 2, 3, 6, 8, 4, 0
CONTROL_LINES = {MOSI, CLK, CS, BUSY, RST, RAIL}
REPEATS = 8
EDGE_DELAY = 0.0002       # seconds between clock edges (bit-bang, SPI is static logic)

PINMUX = "/sys/kernel/debug/pinctrl/pinctrl-rockchip-pinctrl/pinmux-pins"


def die(msg):
    sys.exit(f"error: {msg}")


def free_pins_from_pinmux():
    """Return {(bank, line)} of pins whose mux is unclaimed, per pinctrl debugfs."""
    if not os.path.exists(PINMUX):
        subprocess.run(["mount", "-t", "debugfs", "none", "/sys/kernel/debug"],
                       capture_output=True)
    if not os.path.exists(PINMUX):
        die(f"{PINMUX} not available (debugfs). Refusing to scan without the pinmux check.")
    free = set()
    with open(PINMUX) as f:
        for line in f:
            m = re.match(r"pin \d+ \(gpio(\d)-(\d+)\):\s*(.*)", line)
            if not m:
                continue
            bank, ln, rest = int(m.group(1)), int(m.group(2)), m.group(3)
            if "(MUX UNCLAIMED)" in rest:
                free.add((bank, ln))
    if not free:
        die("pinmux table parsed but no unclaimed pins found; format changed?")
    return free


def rockchip_chips():
    """[(bank, path)] for the SoC's gpio banks, label 'gpioN'."""
    out = []
    for path in sorted(glob.glob("/dev/gpiochip*")):
        try:
            with gpiod.Chip(path) as chip:
                label = chip.get_info().label
        except OSError:
            continue
        m = re.fullmatch(r"gpio(\d)", label)
        if m:
            out.append((int(m.group(1)), path))
    return out


def main():
    if os.geteuid() != 0:
        die("run as root")
    free = free_pins_from_pinmux()

    # --- SX1262 control lines
    ctl = gpiod.request_lines(CHIP1, consumer="miso-scan", config={
        MOSI: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.INACTIVE),
        CLK:  gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.INACTIVE),
        CS:   gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE),
        RST:  gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE),
        BUSY: gpiod.LineSettings(direction=Direction.INPUT),
        RAIL: gpiod.LineSettings(direction=Direction.AS_IS),
    })
    if ctl.get_value(RAIL) != Value.ACTIVE:
        die("LoRa rail (GPIO1_A4) is off. Run: sudo aio lora on")

    # --- candidate lines: free in pinmux, unused by the kernel, not our controls
    reqs = []          # (bank, request, [lines])
    total = 0
    for bank, path in rockchip_chips():
        chip = gpiod.Chip(path)
        lines = []
        for ln in range(chip.get_info().num_lines):
            if bank == 1 and ln in CONTROL_LINES:
                continue
            if (bank, ln) not in free:
                continue
            if chip.get_line_info(ln).used:
                continue
            lines.append(ln)
        chip.close()
        if not lines:
            continue
        try:
            req = gpiod.request_lines(path, consumer="miso-scan", config={
                ln: gpiod.LineSettings(direction=Direction.AS_IS) for ln in lines})
        except OSError as e:
            print(f"gpio{bank}: could not request {len(lines)} lines ({e}), skipping bank")
            continue
        reqs.append((bank, req, lines))
        total += len(lines)
    print(f"sampling {total} free GPIO lines on {len(reqs)} banks "
          f"(GPIO1_A0, the SoC's own SPI4 MISO, {'included' if any(b == 1 and 0 in l for b, _, l in reqs) else 'not free'})")

    # reset pulse, wait for BUSY low
    ctl.set_value(RST, Value.INACTIVE); time.sleep(0.01)
    ctl.set_value(RST, Value.ACTIVE); time.sleep(0.05)
    for _ in range(100):
        if ctl.get_value(BUSY) == Value.INACTIVE:
            break
        time.sleep(0.001)
    else:
        print("warning: BUSY stayed high after reset; the chip may not be powered")

    def sample_all():
        """One snapshot of every candidate line -> list of 0/1 in fixed order."""
        snap = []
        for bank, req, lines in reqs:
            vals = req.get_values(lines)
            snap.extend(1 if v == Value.ACTIVE else 0 for v in vals)
        return snap

    def transaction(select):
        """Clock GetStatus (0xC0, 0x00); sample all lines at each of the 16 high edges."""
        ctl.set_value(CS, Value.INACTIVE if select else Value.ACTIVE)
        time.sleep(EDGE_DELAY)
        samples = []
        for byte in (0xC0, 0x00):
            for i in range(7, -1, -1):
                ctl.set_value(MOSI, Value.ACTIVE if (byte >> i) & 1 else Value.INACTIVE)
                time.sleep(EDGE_DELAY)
                ctl.set_value(CLK, Value.ACTIVE)
                time.sleep(EDGE_DELAY)
                samples.append(sample_all())
                ctl.set_value(CLK, Value.INACTIVE)
                time.sleep(EDGE_DELAY)
        ctl.set_value(CS, Value.ACTIVE)
        time.sleep(0.002)
        return samples   # 16 x N

    def patterns(runs):
        """runs: REPEATS x 16 x N  ->  per line: list of 16-bit patterns per repeat."""
        n = len(runs[0][0])
        per_line = []
        for idx in range(n):
            pats = []
            for run in runs:
                bits = "".join(str(snap[idx]) for snap in run)
                pats.append(bits)
            per_line.append(pats)
        return per_line

    selected = patterns([transaction(True) for _ in range(REPEATS)])
    deselected = patterns([transaction(False) for _ in range(REPEATS)])

    names = [f"GPIO{bank}_{'ABCD'[ln // 8]}{ln % 8} (gpio{bank} line {ln})"
             for bank, _, lines in reqs for ln in lines]

    hits, noise = [], []
    for idx, name in enumerate(names):
        sel, desel = selected[idx], deselected[idx]
        consistent = len(set(sel)) == 1
        nonconst = consistent and sel[0] not in ("0" * 16, "1" * 16)
        if nonconst:
            quiet_when_deselected = (len(set(desel)) == 1 and desel[0] in ("0" * 16, "1" * 16)) \
                or desel[0] != sel[0]
            hits.append((name, sel[0], desel[0], quiet_when_deselected))
        elif not consistent:
            noise.append((name, len(set(sel))))

    print()
    print(f"GetStatus x{REPEATS} with CS low, then x{REPEATS} with CS high, 16 samples each.")
    if hits:
        print("LINES THAT REPRODUCE A STABLE PATTERN WHILE THE CHIP IS SELECTED:")
        for name, pat, dpat, quiet in hits:
            verdict = "MISO candidate" if quiet else "stable but also present when deselected (suspicious)"
            print(f"  {name}: CS low {pat[:8]} {pat[8:]}   CS high {dpat[:8]} {dpat[8:]}   -> {verdict}")
    else:
        print("No free GPIO line reproduces a stable, non-constant pattern in step with the")
        print("SX1262 clock. Its MISO does not reach any free SoC pin on this module.")
    if noise:
        print(f"({len(noise)} lines changed between repeats without a stable pattern: "
              + ", ".join(n for n, _ in noise[:8]) + (" ..." if len(noise) > 8 else "") + ")")
    print(f"BUSY at the end: {'high' if ctl.get_value(BUSY) == Value.ACTIVE else 'low'}")

    for _, req, _ in reqs:
        req.release()
    ctl.release()


if __name__ == "__main__":
    main()
