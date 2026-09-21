#!/usr/bin/env python3
"""Add the HackerGadgets AIO v2 nodes (and optionally your battery's data) to a compiled
rk3588s-radxa-cm5-uconsole.dtb, without a kernel rebuild.

Only named nodes are touched; phandles are read from the DTB, never guessed. Every step
checks whether it is already applied, so the script can be re-run on a DTB it produced
earlier (for example to add the battery values to an existing GPS DTB).

Steps:
  1. UART2 on GPIO0_B5/B6 (uart2m0) for the AIO GPS                  -> /dev/ttyS2
  2. SPI4 left (or put back to) disabled. Earlier versions of this script enabled it
     with a spidev child for the AIO's LoRa SX1262. LoRa does not work on a Radxa CM5
     (as far as traced, MISO has no path; see docs/aio-v2.md), and with ClockworkPi's
     4G board in the slot those lines carry the modem's PCM interface, so an enabled
     SPI4 would drive against the modem. A DTB patched by an old version gets SPI4
     disabled again.
  3. UART4 (serial console ttyS4 on GPIO1_B2/B3) disabled and GPIO1_B3 hogged LOW:
     that pin is PA_EN on the uConsole mainboard, the amplifier enable, and the AW8110
     hisses on battery while the console drives it. You lose the serial console.
     => remove console=ttyS4,1500000 from the kernel command line.
     Skip this step with --keep-console.
  4. I2C7 on GPIO3_D2/D3 (i2c7m2) with a PCF85063A child at 0x51: the CM4 SDA0/SCL0
     pair, the only I2C on the mPCIe slot, where the AIO RTC should sit. Untested;
     a missing chip makes the rtc probe fail harmlessly, the bus stays usable.
  5. Battery data in the simple-battery node (only with --battery-mah). The upstream DTS
     describes two 18650 cells (6700 mAh, 24.79 Wh, 2.9 V min). Userspace (upower etc.)
     reads these as charge_full_design / energy_full_design / voltage_min_design; the
     AXP fuel gauge does not, its capacity registers are set by axp-battery-config.service.

Usage:
  patch-uconsole-dtb.py <input.dtb> <output.dtb> [--keep-console]
                        [--battery-mah 10000 [--battery-mwh 37000] [--battery-vmin-mv 3200]]

Always apply it to the DTB from your own kernel build, then diff the two decompiled trees
(see docs/aio-v2.md). Requires dtc in PATH.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

ap = argparse.ArgumentParser(description="Patch AIO v2 (and battery) nodes into a uConsole CM5 DTB.")
ap.add_argument("src", help="input .dtb (from your own build)")
ap.add_argument("dst", help="output .dtb")
ap.add_argument("--keep-console", action="store_true",
                help="leave UART4 (serial console) enabled and do not hog PA_EN low")
ap.add_argument("--battery-mah", type=int, metavar="MAH",
                help="pack capacity in mAh for charge-full-design-microamp-hours")
ap.add_argument("--battery-mwh", type=int, metavar="MWH",
                help="pack energy in mWh (default: mAh x 3.7 V)")
ap.add_argument("--battery-vmin-mv", type=int, metavar="MV",
                help="voltage-min-design in mV (default: leave as is)")
args = ap.parse_args()

# Plausibility: the flags take mAh / mWh / mV and are multiplied by 1000 below.
# A value in micro units (e.g. 3200000 for 3.2 V) would silently become a 3200 V label.
if args.battery_mah is not None and not 500 <= args.battery_mah <= 50000:
    sys.exit(f"--battery-mah {args.battery_mah}: expected 500..50000 mAh (milliamp-hours, e.g. 10000)")
if args.battery_mwh is not None and not 1500 <= args.battery_mwh <= 250000:
    sys.exit(f"--battery-mwh {args.battery_mwh}: expected 1500..250000 mWh (milliwatt-hours, e.g. 37000)")
if args.battery_vmin_mv is not None and not 2500 <= args.battery_vmin_mv <= 4500:
    sys.exit(f"--battery-vmin-mv {args.battery_vmin_mv}: expected 2500..4500 mV (millivolts, e.g. 3200)")

dts = subprocess.run(["dtc", "-I", "dtb", "-O", "dts", args.src],
                     capture_output=True, text=True, check=True).stdout
changes = []


def phandle_of(node_name):
    m = re.search(r'\t' + re.escape(node_name) + r' \{\n(?:.*\n)*?\t*phandle = <(0x[0-9a-f]+)>;', dts)
    if not m:
        sys.exit(f"node {node_name} not found")
    return int(m.group(1), 16)


def node_span(header):
    """Start/end offsets of the node body that begins with `header` (one indentation level)."""
    i = dts.index(header)
    indent = header[:len(header) - len(header.lstrip('\t'))]
    j = dts.index('\n' + indent + '};\n', i)
    return i, j


def patch_node(header, edits):
    """Apply (old, new) replacements inside one node. `old` may be a compiled regex."""
    global dts
    i, j = node_span(header)
    body = dts[i:j]
    for old, new in edits:
        if isinstance(old, re.Pattern):
            if not old.search(body):
                sys.exit(f"pattern {old.pattern!r} not found in {header.strip()}")
            body = old.sub(new, body, count=1)
        else:
            if old not in body:
                sys.exit(f"'{old.strip()}' not found in {header.strip()}")
            body = body.replace(old, new, 1)
    dts = dts[:i] + body + dts[j:]


def next_phandle():
    return max(int(x, 16) for x in re.findall(r'phandle = <0x([0-9a-f]+)>', dts)) + 1


# ---------------------------------------------------------------- 1) UART2 for the GPS
if '\t\t\tuart2m0-xfer {' in dts:
    ph_uart = phandle_of("uart2m0-xfer")
else:
    pull_up = phandle_of("pcfg-pull-up")
    ph_uart = next_phandle()
    dts = dts.replace('\t\t\tuart2m1-xfer {', f'''\t\t\tuart2m0-xfer {{
\t\t\t\trockchip,pins = <0x00 0x0d 0x0a 0x{pull_up:x} 0x00 0x0e 0x0a 0x{pull_up:x}>;
\t\t\t\tphandle = <0x{ph_uart:x}>;
\t\t\t}};

\t\t\tuart2m1-xfer {{''', 1)
    changes.append(f"uart2m0-xfer pinctrl added (phandle 0x{ph_uart:x})")

edits = [(re.compile(r'\t\tpinctrl-0 = <0x[0-9a-f]+>;'), f'\t\tpinctrl-0 = <0x{ph_uart:x}>;')]
i, j = node_span('\tserial@feb50000 {')
if 'status = "disabled";' in dts[i:j]:
    edits.append(('\t\tstatus = "disabled";', '\t\tstatus = "okay";'))
    changes.append("UART2 (serial@feb50000) enabled on uart2m0 -> /dev/ttyS2")
else:
    changes.append("UART2 already enabled, pinctrl re-pointed at uart2m0")
patch_node('\tserial@feb50000 {', edits)

# ---------------------------------------------------------------- 2) SPI4 stays disabled
i, j = node_span('\tspi@fecb0000 {')
body = dts[i:j]
if 'spidev@0 {' in body:
    # a DTB patched by an earlier version: remove our spidev child, disable the bus
    body = re.sub(r'\n\n\t\tspidev@0 \{\n(?:.*\n)*?\t\t\};', '', body)
    body = body.replace('\t\tstatus = "okay";', '\t\tstatus = "disabled";', 1)
    dts = dts[:i] + body + dts[j:]
    changes.append("SPI4 (spi@fecb0000) disabled again, spidev@0 removed (LoRa unavailable; the 4G board's PCM lives on these lines)")
elif 'status = "okay";' in body:
    changes.append("SPI4 is enabled in this DTB but not by this script; left alone")
else:
    changes.append("SPI4 left disabled")

# ---------------------------------------------------------------- 3) UART4 off, PA_EN hogged low
if args.keep_console:
    changes.append("UART4 left enabled (--keep-console); PA_EN not hogged")
else:
    i, j = node_span('\tserial@feb70000 {')
    if 'status = "okay";' in dts[i:j]:
        patch_node('\tserial@feb70000 {', [('\t\tstatus = "okay";', '\t\tstatus = "disabled";')])
        changes.append("UART4 (serial@feb70000) disabled: no serial console, drop console=ttyS4 from the cmdline")
    else:
        changes.append("UART4 already disabled")
    if 'pa-en-hog {' not in dts:
        i, j = node_span('\t\tgpio@fec20000 {')
        dts = dts[:j] + '''

\t\t\tpa-en-hog {
\t\t\t\tgpio-hog;
\t\t\t\tgpios = <0x0b 0x00>;
\t\t\t\toutput-low;
\t\t\t\tline-name = "PA_EN";
\t\t\t};''' + dts[j:]
        changes.append("PA_EN (GPIO1_B3) hogged low")
    else:
        changes.append("PA_EN hog already present")

# ---------------------------------------------------------------- 4) I2C7 for the AIO RTC
if '\t\t\ti2c7m2-xfer {' in dts:
    ph_i2c = phandle_of("i2c7m2-xfer")
else:
    smt = phandle_of("pcfg-pull-none-smt")
    ph_i2c = next_phandle()
    dts = dts.replace('\t\t\ti2c7m0-xfer {', f'''\t\t\ti2c7m2-xfer {{
\t\t\t\trockchip,pins = <0x03 0x1a 0x09 0x{smt:x} 0x03 0x1b 0x09 0x{smt:x}>;
\t\t\t\tphandle = <0x{ph_i2c:x}>;
\t\t\t}};

\t\t\ti2c7m0-xfer {{''', 1)
    changes.append(f"i2c7m2-xfer pinctrl added (phandle 0x{ph_i2c:x})")

edits = [(re.compile(r'\t\tpinctrl-0 = <0x[0-9a-f]+>;'), f'\t\tpinctrl-0 = <0x{ph_i2c:x}>;')]
i, j = node_span('\ti2c@fec90000 {')
if 'status = "disabled";' in dts[i:j]:
    edits.append(('\t\tstatus = "disabled";', '''\t\tstatus = "okay";

\t\trtc@51 {
\t\t\tcompatible = "nxp,pcf85063a";
\t\t\treg = <0x51>;
\t\t};'''))
    changes.append("I2C7 (i2c@fec90000) enabled on i2c7m2 with rtc@51 (PCF85063A) -> AIO RTC retest")
else:
    changes.append("I2C7 already enabled, pinctrl re-pointed at i2c7m2")
patch_node('\ti2c@fec90000 {', edits)

# ---------------------------------------------------------------- 5) battery data
if args.battery_mah:
    mah = args.battery_mah
    mwh = args.battery_mwh if args.battery_mwh else round(mah * 3.7)
    edits = [
        (re.compile(r'\t\tcharge-full-design-microamp-hours = <0x[0-9a-f]+>;'),
         f'\t\tcharge-full-design-microamp-hours = <0x{mah * 1000:x}>;'),
        (re.compile(r'\t\tenergy-full-design-microwatt-hours = <0x[0-9a-f]+>;'),
         f'\t\tenergy-full-design-microwatt-hours = <0x{mwh * 1000:x}>;'),
    ]
    desc = f"battery: {mah} mAh, {mwh} mWh"
    if args.battery_vmin_mv:
        edits.append((re.compile(r'\t\tvoltage-min-design-microvolt = <0x[0-9a-f]+>;'),
                      f'\t\tvoltage-min-design-microvolt = <0x{args.battery_vmin_mv * 1000:x}>;'))
        desc += f", vmin {args.battery_vmin_mv} mV"
    patch_node('\tbattery {', edits)
    changes.append(desc)
elif args.battery_mwh or args.battery_vmin_mv:
    sys.exit("--battery-mwh / --battery-vmin-mv need --battery-mah")

# ---------------------------------------------------------------- compile
with tempfile.NamedTemporaryFile("w", suffix=".dts", delete=False) as f:
    f.write(dts)
    tmp = f.name
r = subprocess.run(["dtc", "-I", "dts", "-O", "dtb", "-o", args.dst, tmp], capture_output=True, text=True)
os.unlink(tmp)
if r.returncode:
    sys.exit(r.stderr)
for c in changes:
    print(" -", c)
print(f"written: {args.dst}")
