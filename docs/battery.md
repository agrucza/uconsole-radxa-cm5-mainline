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
| Fuel-gauge pack capacity | what your pack **delivers in this system**, not its label | registers 0xE0/0xE1 |

The capacity encoding: `capacity_mAh / 1.456`, rounded, as a 16-bit value; bit 7 of the high byte marks it valid. The unit ships with the value measured for this fork's pack, a cell labelled 10 000 mAh that delivers 7 583 mAh between a terminated charge and the 3.50 V guard (the run is described below):

```
measured: 7 583 mAh / 1.456 = 5208 = 0x1458  ->  0xE0 = 0x14 | 0x80 = 0x94,  0xE1 = 0x58
label:   10 000 mAh / 1.456 = 6868 = 0x1AD4  ->  0xE0 = 0x9A, 0xE1 = 0xD4   (do not use; see below)
```

Edit the two `i2cset` bytes in the unit for your pack, after measuring it, and confirm the I²C bus number with `i2cdetect -l` (the adapter named `i2c-axp`; it is 9 in this build but depends on probe order). Then:

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

Measure it instead of guessing. This is the procedure, followed by the result for this pack:

1. Charge until the AXP has terminated. With an unpatched kernel the sysfs `status` keeps saying `Charging` even then, because the driver derives it from the current-direction flag, which the 1 mA residual current still trips; the chip's own flag is register 0x01 bit 6, `sudo i2cget -f -y 9 0x34 0x01` reading for example `0x30` means "not charging or charge finished". [`kernel/0001-axp20x_battery-report-full-after-charge-termination.patch`](../kernel/0001-axp20x_battery-report-full-after-charge-termination.patch) makes the driver consult that flag and report `Full`; with it applied, `status` is the check. The charge LED going out says the same thing without a terminal.
2. Let the run go until the guard powers the device off. With the [battery log](#a-permanent-battery-log) installed nothing has to be started by hand: the run is the stretch of `Discharging` lines between the unplug and the shutdown marker. Sum `current_now` (absolute value, it is negative while discharging) over the minutes and divide by 60 000 for mAh.
3. Put that number through the formula above and write the two bytes into `axp-battery-config.service`. Compare percentage against voltage on the next run.
4. Do not trust readings from the last minutes of a run; once reads fail the mainboard is already browning out.

The percentage reported by the AXP is register `0xB9` (bits 6:0 the percentage; bit 7 set means the gauge is still calculating); `capacity` in sysfs is that value.

### The measured result: 7 583 mAh, and why that is not 10 000

Run of 2026-09-21, done exactly as above: charge terminated by the AXP (LED out, register 0x01 bit 6 clear, `Full` with the patched driver), then normal use with the display on and WiFi up until the 3.50 V guard powered the machine off.

| | |
|---|---|
| Start | 4.169 V resting, 15:58 |
| End | 3.491 V under load, 21:45, guard poweroff |
| Duration | 348 minutes |
| Average current | 1.31 A |
| **Delivered** | **7 583 mAh** (sum of `current_now` per minute / 60 000) |

The label says 10 000 mAh. The two numbers measure different things, and this run cannot say how far apart the cell and its label really are. What it does show:

- **The cutoff is different.** A label capacity is taken down to the cell's minimum voltage, typically 2.75 to 3.0 V, at a gentle current. This system stops at 3.50 V terminal voltage because the mainboard's 3.3 V rail falls out of regulation below about 3.4 V. Whatever the cell holds below that point is not available here.
- **The load drop is measured.** Unplugging at 15:57 took the terminal voltage from 4.169 V at rest to 4.060 V at 1.32 A within a minute: 109 mV, about 83 mΩ for cell, protection board, leads and the AXP's sense path together. So at the guard's 3.49 V the cell itself stood near 3.60 V.
- **The measuring instrument is the AXP's ADC**, 1 mA steps and an unknown gain error, and its units are the units the gauge divides by.

How much capacity sits below 3.6 V on this cell was not measured; generic lithium discharge curves suggest a noticeable share, but that is an estimate, not a result. What the run establishes is the only figure the system can use: 7 583 mAh between "charger finished" and "guard fires" under this load.

For the fuel gauge only that delivered number matters: the percentage is counted charge divided by the register value, in the AXP's own units. With the label programmed the gauge reported 34 % on an empty cell; with the measured value it has a chance of being right.

### The gauge's two modes, and why the guard rules one out

The gauge control register `0xB8` reads `0xC0` out of reset: bit 7 enables the gauge, bit 6 the coulomb counter. Bit 5 switches on the chip's **self-calibration**: instead of trusting the capacity in 0xE0/0xE1, the chip tries to learn it by watching one complete discharge from charge termination down to its own cutoff, 3.2 V. While that cycle is open the result register `0xB9` holds `0xE4`, bit 7 "calculating" with a placeholder 100, and `capacity` in sysfs reads 100 whatever the state of the cell.

On this machine the cycle can never close. The 3.50 V guard powers the system off before the chip's 3.2 V, and without the guard the mainboard would brown out at about 3.4 V, still above it. So with bit 5 set the gauge shows 100 from full to empty, and every terminated charge opens a fresh cycle. Observed twice: during the run of 2026-09-21 (after a battery pull, `0xB9 = 0xE4` for the whole run), and again on 2026-09-23 after calibration had been switched on deliberately two days earlier: a restart of the gauge (`0xB8` written `0x40` then back) produced one credible reading, 43 % at 3.92 V while charging, the charge terminated overnight, and the next morning `0xB9` was back at `0xE4` and `capacity` at 100 while the cell was already at 3.88 V under a 1.3 A load.

The working configuration is therefore the reset default, `0xB8 = 0xC0`, self-calibration **off**, and the measured usable capacity in 0xE0/0xE1. The chip then anchors 100 % at each charge termination and counts down against 7 583 mAh, which is exactly the range the machine can use. Restoring it:

```bash
sudo i2cset -f -y 9 0x34 0xB8 0xC0
sudo i2cget -f -y 9 0x34 0xB9        # bit 7 clear once a result exists
```

Nothing in the config unit touches 0xB8, so a reset or battery pull lands on the same setting; a leftover open cycle from before is reset by the `0x40` / `0xC0` write pair. Whether the percentage then falls about one point per 3.5 minutes at 1.3 A and reaches a low value where the guard fires is the check for the next full charge and discharge.

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

## A permanent battery log

Two of the three discharge runs in this document were spoiled by the logger, once by a desktop suspend, once by starting it an hour late. [`runtime/battery/battery-log`](../runtime/battery/battery-log) removes the "start the logger" step: a timer appends one line a minute to `/var/log/battery.csv`, from boot to shutdown, whatever the machine is doing. A run is then simply a time window in that file.

```
time,status,ac,voltage_uV,current_uA,capacity_pct,gauge_reg
2026-09-24T08:06:00+02:00,boot,0,3909400,-1276000,100,0x64
2026-09-24T08:07:00+02:00,Discharging,0,3909400,-1277000,100,0x64
```

`status` is the driver's status, or the markers `boot` and `shutdown`; a gap without a `shutdown` line before it is a crash or a brown-out. `gauge_reg` is the AXP's register 0xB9 raw, when `i2c-tools` is installed. It is there to catch the trap described above: a value of `0xE4`, bit 7 with 100 underneath, that never moves through a discharge. Bit 7 alone is not the alarm; while charging the chip sets it next to a live percentage (`0xDB` next to 91 % at the first logged minute). Values the AXP does not deliver (the intermittent `-6` reads) are logged as empty fields, never as a missing line, so the minute count stays right.

```bash
sudo install -m 755 runtime/battery/battery-log /usr/local/bin/
sudo cp runtime/battery/battery-log.{service,timer} runtime/battery/battery-log-shutdown.service /etc/systemd/system/
sudo cp runtime/battery/battery-log.logrotate /etc/logrotate.d/battery-log
sudo systemctl enable --now battery-log.timer battery-log-shutdown.service
```

Reading it back with `awk`: the charge drawn between two points in time, and the moments the status changed, which mark the start of a charge or a discharge:

```bash
awk -F, '$1>="2026-09-24T08:00" && $1<="2026-09-24T14:00" && $5<0 {s+=-$5; n++} END{printf "%.0f mAh over %d min (avg %.2f A)\n", s/60000, n, s/n/1e6}' /var/log/battery.csv
awk -F, 'NR>1 && prev!="" && $2!=prev {print $1, prev" -> "$2, $4/1e6" V"} {prev=$2}' /var/log/battery.csv
```

One line a minute is about 30 MB a year; logrotate keeps monthly, compressed files for two years. The log is separate from the guard on purpose: the guard is safety code and stays small, and a logging failure must never touch it.

## Intermittent `-6` reads

`axp20x-battery` occasionally returns `-6` (ENXIO) on a read. The AXP sits on a bit-banged I²C bus without external pull-ups. It is intermittent and has not caused a problem; a DTB variant with internal pull-ups and a 25 kHz bus is prepared but has not been needed.

## The 10 Ah swap

One JS 1260110 cell (3.7 V, 10 000 mAh, 37 Wh, with protection board) replaces the two 18650 holders on the original battery board, under a 3D-printed back cover. Nothing else changes: the AXP still sees one cell, charges at 2.1 A to 4.2 V, and the settings above give it the right capacity and a safe cutoff.

If you go the other way and parallel unprotected pouch cells (9858102, 3.85 V / 4.4 V chemistry, was considered as an alternative): a 1S BMS rated for at least 10 A, a 5 A fuse in the positive lead (polyfuse MF-R500 or a blade fuse), match the cells to within 50 mV before paralleling, keep the 4.2 V charge cutoff (about 80 % of nominal capacity for that chemistry, with margin to the cell limit), 0.75 mm² wire throughout, one wire per tab, and Y-splices away from the cells.

## Shutdown hook

The upstream `runtime/axp-off.sh` shutdown hook cuts the AXP rails at poweroff. Once the battery path was sound, warm reboot and poweroff also worked without it; it is kept installed because the upstream README documents it and it costs nothing.
