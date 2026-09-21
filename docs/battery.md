# Battery and AXP228 configuration

The uConsole is a 1S system: the mainboard's AXP228 sees one cell (or the two 18650s in parallel) and charges it to 4.2 V at up to 2.1 A. Everything here applies to the stock battery board too, but was worked out while replacing the 18650s with a single 10 Ah pouch cell.

## The one lesson that matters

**A sagging supply produces exactly the symptoms of a broken device tree.** With the battery at 5 % (3.4 V) for two days and a high-resistance battery lead, the panel stayed uniformly grey and the keyboard never enumerated (`command interface is busy`, USB `-71` on the keyboard hub), whatever kernel or DTB was booted. Two days went into device-tree theories. A cold power-up with a working charger connected brought the device back, and the same DTS has worked ever since.

Check the battery before touching anything else:

```bash
grep -H . /sys/class/power_supply/axp20x-battery/{voltage_now,capacity,status}
grep -H . /sys/class/power_supply/axp22x-ac/online
```

Below roughly 3.5 V under load, do not trust any other symptom. Also: **build kernels on the Radxa IO board (12 V), not in the uConsole on battery.** With a weak battery the AXP cuts power hard under full CPU load.

## Charger

The uConsole negotiates no USB PD. The charger must offer 5 V by default, and it needs to deliver about 3 A for the full 2.1 A charge current. An Anker Prime 200 W GaN charger works; one other PD-only charger delivered nothing at all (AXP register 0x00 read 0x00, no VBUS). If the orange LED stays dark while charging, the AXP's LED bit is not set; see [below](#the-orange-charge-led).

## Settings that do not survive a power loss

The AXP228 keeps its registers only while powered. Three settings are worth re-applying on every boot with [`runtime/battery/axp-battery-config.service`](../runtime/battery/axp-battery-config.service):

| Setting | Value | Where |
|---|---|---|
| Charge LED | driven by the charger instead of dark | register 0x32, bit 3 (see below) |
| Discharge cutoff | 3.2 V instead of the default 2.9 V | `voltage_min` in sysfs (register 0x31 = 0x06) |
| Fuel-gauge pack capacity | your pack in mAh | registers 0xE0/0xE1 |

The capacity encoding: `capacity_mAh / 1.456`, rounded, as a 16-bit value; bit 7 of the high byte marks it valid.

```
10 000 mAh / 1.456 = 6868 = 0x1AD4
0xE0 = 0x1A | 0x80 = 0x9A
0xE1 = 0xD4
```

Edit the two `i2cset` bytes in the unit for your pack and confirm the I²C bus number with `i2cdetect -l` (the adapter named `i2c-axp`; it is 9 in this build but depends on probe order). Then:

```bash
sudo apt install -y i2c-tools
sudo cp runtime/battery/axp-battery-config.service /etc/systemd/system/
sudo systemctl enable --now axp-battery-config.service
```

The percentage is only meaningful after one full charge/discharge cycle, and only if the capacity value matches what the cell really delivers. Until then `voltage_now` is the number to watch: about 4.1 V full, 3.5 V empty for practical purposes (see the discharge run below).

Check what the AXP currently holds:

```bash
E0=$(sudo i2cget -f -y 9 0x34 0xE0); E1=$(sudo i2cget -f -y 9 0x34 0xE1)
echo "valid=$(( (E0 >> 7) & 1 ))  capacity=$(( ((E0 & 0x7f) * 256 + E1) * 1456 / 1000 )) mAh"
```

## A measured discharge: why 34 % at 3.34 V is not real

Logged once a minute with the display on, WiFi up, from a fresh charge until the mainboard gave out (2026-09-19, the 10 Ah cell with the capacity registers set to 10 000 mAh):

| Time | `voltage_now` | `capacity` | What it means |
|---|---|---|---|
| 20:59 to 21:59 | 3.97 → 3.91 V | 100 % for 61 minutes | gauge anchored too high: a 1S cell at 3.9 V under load is 85 to 90 %, not full |
| 21:59 to 02:15 | 3.91 → 3.53 V | 99 → 42 %, exactly 4.5 min per percent | pure charge counting, independent of voltage |
| 02:05 to 02:25 | 3.61 → 3.34 V | 44 → 34 % | the knee, the cell is empty |
| 02:26 onwards | reads fail with ENXIO | log keeps running | mainboard 3.3 V rail dropping out, CM5 still alive, network gone |

Two things push the percentage the same way. The gauge started 10 to 15 points too high, and the AXP counted less charge between "full" and the knee than the 10 Ah in its capacity registers. The percentage is simply counted charge divided by that register value, so the register has to hold what the AXP counts in this system, not the cell's label. Several things make that smaller than the label without the cell being at fault: the 4.15 V charge limit, the voltage drop over protection board and leads under load, the AXP's own current measurement, and possibly an incomplete charge at the start. The 61-minute plateau at 100 % also hides an unknown amount of consumption, so this run cannot say how much was actually counted.

Measure it instead of guessing:

1. Charge until the AXP has terminated. With an unpatched kernel the sysfs `status` keeps saying `Charging` even then, because the driver derives it from the current-direction flag, which the 1 mA residual current still trips; the chip's own flag is register 0x01 bit 6, `sudo i2cget -f -y 9 0x34 0x01` reading for example `0x30` means "not charging or charge finished". [`kernel/0001-axp20x_battery-report-full-after-charge-termination.patch`](../kernel/0001-axp20x_battery-report-full-after-charge-termination.patch) makes the driver consult that flag and report `Full`; with it applied, `status` is the check. The charge LED going out says the same thing without a terminal.
2. Log `voltage_now`, `current_now` and `capacity` once a minute until the guard powers the device off. Sum `current_now` (absolute value, it may be negative while discharging) over the minutes and divide by 60 000 for mAh.
3. Put that number through the formula above and write the two bytes into `axp-battery-config.service`. Compare percentage against voltage on the next run.
4. Do not trust readings from the last minutes of a run; once reads fail the mainboard is already browning out.

The percentage reported by the AXP is register `0xB9` (bits 6:0 the percentage; bit 7 set means the gauge is still calculating); `capacity` in sysfs is that value.

## The orange charge LED

Upstream lists the charge LED as dark although charging works. The reason is in AXP228 register 0x32, which reads 0x43 out of reset: bit 3 selects who drives the CHGLED pin, 0 for the manual pattern in bits 5:4, 1 for the charger state machine, and the default is manual with the pattern set to off. Setting bit 3 hands the pin to the charger: on while charging, off when the charge is complete or no charger is present. The unit above does that with a read-modify-write so the rest of the register is untouched:

```bash
sudo i2cset -f -y -m 0x08 9 0x34 0x32 0x08     # bit 3 on; 0x43 -> 0x4b
```

Verified 2026-09-20 against the AXP228 datasheet (REG32H) and on the device: the manual patterns in bits 5:4 (11 = on, 01 = 0.5 Hz, 10 = 2 Hz) light and blink the LED, and in charger mode it is on while charging and dark once the charge has tapered out. In charger mode the datasheet's "type A" indication applies: low while charging, high-Z when not, 0.5 Hz blink for a battery fault, 2 Hz for input over-voltage; bit 4 of REG34H would select type B. The poweroff hook writes 0xC3 and thereby clears the bit; that only happens at shutdown, and the unit sets it again at the next boot.

## Clean shutdown before the mainboard browns out

[`runtime/battery/battery-guard`](../runtime/battery/battery-guard) powers the system off cleanly at **3.50 V** on battery. It runs once a minute from a timer and does nothing on external power.

Why 3.50 V and not something closer to the AXP's 3.2 V cutoff: the mainboard's 3.3 V rail is a buck converter fed from the battery. Below about 3.4 V it falls out of regulation and the USB hub, the WiFi dongle and the pull-ups of the AXP's own I²C bus go with it. The CM5, with its own PMIC, keeps running blind. The discharge run below shows this happening. The stretch from 3.50 V down to 3.34 V lasted 12 minutes of a 5.5 hour run, so stopping at 3.50 V costs about 4 %.

The guard also handles the blind case: if the AXP cannot be read for three minutes in a row while on battery, it powers off anyway, because that failure *is* the brown-out. If the sysfs nodes are missing entirely (other kernel, driver not loaded), it does nothing. An earlier version compared an empty string against the threshold when the read failed and silently did nothing, exactly at the moment it was needed.

```bash
sudo install -m 755 runtime/battery/battery-guard /usr/local/bin/
sudo cp runtime/battery/battery-guard.{service,timer} /etc/systemd/system/
sudo systemctl enable --now battery-guard.timer
```

## Intermittent `-6` reads

`axp20x-battery` occasionally returns `-6` (ENXIO) on a read. The AXP sits on a bit-banged I²C bus without external pull-ups. It is intermittent and has not caused a problem; a DTB variant with internal pull-ups and a 25 kHz bus is prepared but has not been needed.

## The 10 Ah swap

One JS 1260110 cell (3.7 V, 10 000 mAh, 37 Wh, with protection board) replaces the two 18650 holders on the original battery board, under a 3D-printed back cover. Nothing else changes: the AXP still sees one cell, charges at 2.1 A to 4.2 V, and the settings above give it the right capacity and a safe cutoff.

If you go the other way and parallel unprotected pouch cells (9858102, 3.85 V / 4.4 V chemistry, was considered as an alternative): a 1S BMS rated for at least 10 A, a 5 A fuse in the positive lead (polyfuse MF-R500 or a blade fuse), match the cells to within 50 mV before paralleling, keep the 4.2 V charge cutoff (about 80 % of nominal capacity for that chemistry, with margin to the cell limit), 0.75 mm² wire throughout, one wire per tab, and Y-splices away from the cells.

## Shutdown hook

The upstream `runtime/axp-off.sh` shutdown hook cuts the AXP rails at poweroff. Once the battery path was sound, warm reboot and poweroff also worked without it; it is kept installed because the upstream README documents it and it costs nothing.
