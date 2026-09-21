# HackerGadgets AIO v2 on the Radxa CM5

The [HackerGadgets AIO v2](https://hackergadgets.com) is an expansion board for the uConsole's Mini-PCIe slot that bundles an RTL-SDR, a LoRa SX1262, a GPS receiver, a PCF85063A RTC, a USB hub and an RJ45 jack. It is designed for the Raspberry Pi CM4 pinout. On a Radxa CM5 **five of the six functions work**. LoRa is not available right now and probably will not work: as far as the routing can be traced, its MISO line arrives at the one module position the CM5 leaves unconnected. The AIO-side pins have not been measured yet. The RTC was long believed blocked too; that was a misreading of the slot's routing, and since 2026-09-20 it runs on I2C7. HackerGadgets has announced a Radxa CM5 variant of the board.

Everything below was verified on Debian 13 with a mainline 7.2.6 kernel built from this repo (see [debian.md](debian.md)).

| Function | Pi side (HackerGadgets) | Radxa CM5 | State |
|---|---|---|---|
| Power rails | GPIO 27 / 16 / 7 / 23 | GPIO1_C5 / A4 / B5 / A7 | ✅ switchable with `aio` |
| GPS | UART0 (BCM14/15) | UART2 m0 = GPIO0_B5/B6 → `/dev/ttyS2` | ✅ works, needs the DTB patch |
| RTL-SDR | USB | USB (AIO hub) | ✅ works |
| USB hub, RJ45 | USB3, RGMII | `usb_host2` via adapter, native GMAC | ✅ works |
| RTC PCF85063A | the slot's I²C = CM4 SDA0/SCL0 | GPIO3_D3/D2 = **I2C7 m2** → `/dev/rtc0` | ✅ works |
| LoRa SX1262 | SPI1 (BCM19/20/21, CE0 BCM18) + IRQ 26, Busy 24, Reset 25 | CLK, MOSI, CS reach GPIO1_A2/A1/A3; **MISO arrives at Connector 1 position 26, NC on the CM5**; SPI4 is left disabled | ❌ not available, probably no path; AIO pins still to be measured |

The full pin translation, and how the mPCIe slot's lines really travel from the AIO to the module, is in [gpio-map.md](gpio-map.md#expansion-slot-mpcie-routing).

---

## Power rails: the `aio` tool

The AIO switches its sub-boards through four enable lines. On the CM5 they are plain GPIOs that nothing in the device tree claims, so a small libgpiod v2 script drives them: [`runtime/aio-v2/aio`](../runtime/aio-v2/aio).

| Rail | Pi GPIO | RK3588S | `gpiochip1` line | Notes |
|---|---|---|---|---|
| `gps` | 27 | GPIO1_C5 | 21 | off by default |
| `lora` | 16 | GPIO1_A4 | 4 | off by default |
| `sdr` | 7 | GPIO1_B5 | 13 | **on** at boot on the CM5 (SoC pad resets pulled up), off only by driving low |
| `usb` | 23 | GPIO1_A7 | 7 | internal USB ports; **never switch off** (fan and WiFi dongle hang off it) |

```bash
sudo apt install -y python3-libgpiod            # libgpiod v2 bindings (Debian 13+)
sudo install -m 755 runtime/aio-v2/aio /usr/local/bin/aio

aio status
sudo aio gps on
sudo aio sdr off
sudo aio all off                                # gps, lora, sdr
```

Two things in the script are deliberate and easy to break:

- **"off" releases the line instead of driving it low** (except for `sdr`). An active low on GPIO1_C5 knocks the keyboard, USB sticks and HDMI DDC off the bus. The kernel keeps the last output state after the request is released, so "on" survives the script exiting.
- **`sdr` is the exception**: HackerGadgets documents all four rails as off until their GPIO is driven high, and on a Pi that holds. On the Radxa CM5 two of the enable pins come out of reset with a pull-up, GPIO1_B5 (SDR) and GPIO1_A7 (USB); Radxa's pinout sheet marks them `_u`, GPS and LoRa are `_d`. So SDR and USB are on from power-up before any software runs, and releasing the SDR line does not switch it off. "off" therefore drives it low. Tested, disturbs nothing. For USB that is the wanted state anyway.

[`runtime/aio-v2/aio-rails.service`](../runtime/aio-v2/aio-rails.service) sets the default state after boot (usb on, sdr off; gps and lora stay released):

```bash
sudo cp runtime/aio-v2/aio-rails.service /etc/systemd/system/
sudo systemctl enable aio-rails.service
```

---

## GPS

The receiver sits on the Pi UART0 pins, which on the CM5 are UART2 in its `m0` pinmux (GPIO0_B5/B6). The upstream device tree leaves UART2 disabled because it never reaches the GPIO header. It does reach the Mini-PCIe slot, which is exactly where the AIO plugs in.

1. Build the AIO DTB (below) and boot it. `/dev/ttyS2` appears.
2. Install `gpsd` and let it manage the rail with [`runtime/aio-v2/gpsd-rail.conf`](../runtime/aio-v2/gpsd-rail.conf):

   ```bash
   sudo apt install -y gpsd gpsd-clients chrony
   sudo mkdir -p /etc/systemd/system/gpsd.service.d
   sudo cp runtime/aio-v2/gpsd-rail.conf /etc/systemd/system/gpsd.service.d/rail.conf
   sudo systemctl daemon-reload
   # /etc/default/gpsd: DEVICES="/dev/ttyS2"
   sudo systemctl enable --now gpsd
   ```

3. A first fix takes one to two minutes. `gpsmon` or `cgps` shows it.
4. `chrony` with `refclock SHM 0 refid GPS` in `/etc/chrony/chrony.conf` picks the fix up from gpsd and, with `rtcsync`, keeps the AIO's RTC trimmed; NTP covers the rest.

---

## RTL-SDR

Pure USB, behind the AIO hub. Blacklist the DVB driver so `librtlsdr` gets the device:

```bash
sudo apt install -y rtl-sdr
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/rtl-sdr-blacklist.conf
sudo aio sdr on
rtl_test -s 2048000            # clean, no dropped samples
```

`rtl_power` across the FM broadcast band is a quick end-to-end check.

The board has a 5 V bias tee for an active antenna or LNA, switched through the RTL2832U itself with an LED to show its state. `rtl_biast -b 1` from the same package should turn it on; not tried here.

---

## USB hub and Ethernet

Both work without any change to the device tree. The RJ45 uses the CM5's native GMAC, the hub sits on the second USB host port through the HackerGadgets adapter.

Known board quirk, per HackerGadgets: AIO v2 boards shipped before 15 January 2026 limit the internal USB-C port to 0.68 A instead of 1.58 A. The fix is a resistor swap (4.3 kΩ, 0402).

---

## RTC: works, on I2C7

For a long time this fork said the RTC was unreachable because "its SDA line sits on the AXP228 interrupt pin". That was wrong, and the mistake is worth recording: it came from reading the AIO's Pi GPIO numbers as 40-pin header pins. The AIO does not sit on the header, it sits in the mPCIe slot, and the slot carries a different set of lines.

What the ClockworkPi schematics say, confirmed by continuity measurements on 2026-09-20 (details in [gpio-map.md](gpio-map.md#expansion-slot-mpcie-routing)):

- BCM 2 and 3 never reach the slot. They are the mainboard's own nets `GPIO2` and `GPIO3` (AXP IRQ and `WL_REG_ON`) and appear only on the 40-pin FPC.
- The slot's only I²C is the CM4 **SDA0/SCL0** pair, mainboard nets `GPIO44/45`, mPCIe pins 50/52. ClockworkPi's own 4G board uses them for its I²C. On the Radxa CM5 they land on Connector 1 positions 82/80, which are **GPIO3_D3/GPIO3_D2 = I2C7 in its `m2` pinmux**. Measured: mPCIe 50 → position 82, mPCIe 52 → position 80.

With I2C7 enabled on `i2c7m2` and a `pcf85063a` node at 0x51, both in the AIO DTS and in the patch script, the chip answered at first boot:

```
rtc-pcf85063 7-0051: POR issue detected, sending a SW reset
rtc rtc0: Power loss detected, invalid time
rtc-pcf85063 7-0051: registered as rtc0
```

The "power loss" lines are expected on a chip that has never been set, or has no coin cell. Set it once from the synchronised system clock and check that it reads back:

```bash
timedatectl | grep -i synchronized      # yes, from GPS/NTP
sudo hwclock -w
sudo hwclock -r
```

Two housekeeping points:

- **Coin cell.** The AIO takes a CR1220. Without it the RTC keeps time only while the AIO is powered, so it survives a warm reboot but not a power-off. With the cell fitted, verify once: full power-off, a minute without power, boot, `hwclock -r` before the network is up.
- **`fake-hwclock`.** Radxa's Debian image ships it as a stand-in for a missing RTC. Its service was already masked on this system; leave it masked or purge the package. `chrony` with `rtcsync` keeps the PCF85063A trimmed from then on.

An early attempt on I2C7 had been dismissed as a wrong turn. It was the right bus; the earlier failure is unexplained. Nothing in this path touches the AXP interrupt.

---

## LoRa: not available, probably no path

Not working right now, and probably not fixable without a wire: everything traced so far says the SX1262's MISO line does not reach the SoC with this AIO, this adapter and this module. The picture rests on three stages with three different kinds of evidence, and it is worth keeping them apart:

| Stage | Claim | Basis |
|---|---|---|
| AIO board | MISO leaves the AIO on mPCIe pin 20 | forced, not measured: on a Raspberry Pi SPI1's MISO exists only on BCM19, the AIO runs Meshtastic on `spidev1.0` there, and ClockworkPi's CM4 adapter puts BCM19 on mainboard net `GPIO29` = mPCIe pin 20 |
| mainboard + HackerGadgets adapter | mPCIe pin 20 arrives at Connector 1 position 26, nowhere else | **measured** 2026-09-20, continuity |
| Radxa CM5 | position 26 connects to nothing | documented by Radxa in two places, the pinout spreadsheet (`radxa_cm5_v2200_pinout.xlsx`, from Radxa's documentation: "Raspberry Pi CM4: GPIO19, Radxa CM5: NC") and the `gpio-line-names` in their DTS, where it is the only header position without a label; consistent with every observation |

Consistent with that, `GetStatus` (0xC0) over `/dev/spidev4.0` (SPI4 was enabled in the DTS at the time; it no longer is) returned a constant `0xff`, and [`tools/sx1262-bitbang.py`](../tools/sx1262-bitbang.py) shows the SoC-side SPI4 `m2` MISO, GPIO1_A0, following whatever bias it is given. CLK, MOSI, CS, IRQ, Busy and Reset all arrive; only the return path is missing.

What is still open is the AIO board itself: continuity from the SX1262 module's MISO pad to mPCIe finger 20, to be measured once the AIO can come out of the running unit. Until then this stays "probably".

Done already, on the module, in software: [`tools/lora-miso-scan.py`](../tools/lora-miso-scan.py). With the LoRa rail on it bit-bangs GetStatus so the SX1262 drives its status byte onto MISO, and at every clock edge samples every GPIO line that is free in the pinmux table and unused by the kernel, on all five SoC banks. A line that reproduces the same non-constant pattern on every repeat while CS is low, and not while CS is high, is MISO arriving somewhere Radxa did not document. Peripheral-owned pins are never touched, so it is safe on the running system. Run on 2026-09-20: 89 free lines on all five banks, the chip alive (BUSY released after reset), no line followed the clock.

Options to make it work, none tried here:

- Wait for HackerGadgets' announced Radxa CM5 variant of the AIO, or ask them.
- A bodge wire from the SX1262 module's MISO pad to a slot line that does reach the CM5, plus `spi-gpio` in the DTS. Which slot line, to be established by measurement first.
- A USB LoRa node.

The meshtasticd configuration that would be correct once the chip is reachable is kept for reference: [`runtime/aio-v2/meshtasticd-aio-v2-lora.yaml`](../runtime/aio-v2/meshtasticd-aio-v2-lora.yaml) (spidev4.0, IRQ gpiochip3/24, Busy 1/6, Reset 1/8) and the rail drop-in [`runtime/aio-v2/meshtasticd-lora-power.conf`](../runtime/aio-v2/meshtasticd-lora-power.conf). Note that the Debian 12 meshtasticd package segfaults on this kernel (built against libgpiod 1, and the kernel has no `CONFIG_GPIO_CDEV_V1`); the Debian 13 package runs.

---

## The AIO device tree

Two ways to get the same tree; pick by what you have.

**From source, if you have the kernel tree:** [`kernel/rk3588s-radxa-cm5-uconsole-aio.dts`](../kernel/rk3588s-radxa-cm5-uconsole-aio.dts) includes the base DTS and overrides five nodes: UART2 on `uart2m0` for the GPS, UART4 disabled with `stdout-path` removed, the `PA_EN` hog on GPIO1_B3, I2C7 on `i2c7m2` with the RTC child, and the battery node for a single 10 Ah cell. SPI4 is deliberately left disabled, see [Other boards in the slot](#other-boards-in-the-slot). Copy it next to the base DTS and add its Makefile line (README, step 2), then:

```bash
DTBS_ONLY=1 KDIR=$PWD ~/build-uconsole-kernel.sh      # seconds, no kernel rebuild
sudo cp arch/arm64/boot/dts/rockchip/rk3588s-radxa-cm5-uconsole-aio.dtb /boot/dtb-7.2/
```

Edit the battery values in the DTS if your pack differs. A full build produces both DTBs anyway.

**From a prebuilt DTB, without a tree:** [`tools/patch-uconsole-dtb.py`](../tools/patch-uconsole-dtb.py) adds the same nodes to a compiled DTB. It decompiles with `dtc`, edits only named nodes, reads phandles from the tree instead of guessing them, and recompiles. Every step checks whether it is already applied, so you can re-run it on a DTB it produced earlier, for instance to add the battery values later. It does up to five things:

| Change | Why | Control |
|---|---|---|
| UART2 enabled on `uart2m0` (GPIO0_B5/B6) | AIO GPS → `/dev/ttyS2` | always |
| SPI4 left disabled; a DTB from an earlier version of the script gets it disabled again | LoRa has no path, and with the 4G board in the slot these lines are the modem's PCM interface | always |
| **UART4 disabled**, GPIO1_B3 hogged low as `PA_EN` | GPIO1_B3 is the amplifier enable on the mainboard. With the console on it the AW8110 hisses on battery. **You lose the serial console.** | default; `--keep-console` skips it |
| I2C7 enabled on `i2c7m2` (GPIO3_D2/D3), `rtc@51` child (PCF85063A) | the mPCIe slot's I²C bus, the AIO RTC → `/dev/rtc0`; see [RTC](#rtc-works-on-i2c7) | always |
| `simple-battery` node updated | upstream describes two 18650 cells (6700 mAh, 24.79 Wh, 2.9 V min). Userspace reads these as `charge_full_design` etc.; the AXP gauge does not (see [battery.md](battery.md)) | only with `--battery-mah`, plus `--battery-mwh` and `--battery-vmin-mv` |

Apply it to the DTB from **your own build**, never to someone else's, and diff the result:

```bash
python3 tools/patch-uconsole-dtb.py /boot/dtb-7.2/rk3588s-radxa-cm5-uconsole.dtb /tmp/uconsole-aio.dtb \
    --battery-mah 10000 --battery-mwh 37000 --battery-vmin-mv 3200      # your pack, or omit
dtc -I dtb -O dts /boot/dtb-7.2/rk3588s-radxa-cm5-uconsole.dtb > /tmp/a.dts
dtc -I dtb -O dts /tmp/uconsole-aio.dtb > /tmp/b.dts
diff /tmp/a.dts /tmp/b.dts          # exactly the changes listed above
sudo cp /tmp/uconsole-aio.dtb /boot/dtb-7.2/rk3588s-radxa-cm5-uconsole-aio.dtb
```

The script prints what it changed and what it found already in place. Decide about the console before you run it: with UART4 disabled, `console=ttyS4,1500000` must go from the boot entry; with `--keep-console` it stays, and so does the amplifier hiss on battery.

Then add a **second** boot entry that points at the new DTB and drops `console=ttyS4,1500000` from the command line. Keep the entry with the unpatched DTB as the fallback; [`runtime/extlinux.conf.example`](../runtime/extlinux.conf.example) shows both. Verify after the reboot:

```bash
ls -l /dev/ttyS2 /dev/rtc0
tr -d '\0' < /sys/firmware/devicetree/base/serial@feb70000/status    # disabled
```

Both paths end in the same tree; the patch-script output has been running on hardware since 2026-09-20, the DTS is the readable form of it. Verify the source build once by decompiling both with `dtc -I dtb -O dts` and diffing: only node order and phandle numbers should differ.

---

## Other boards in the slot

The AIO v2 is not the only thing that goes into the mPCIe slot, and the slot's lines mean something different on every board. Two rules follow, both learned from ClockworkPi's schematic of their own 4G board:

- **SPI4 stays disabled in the AIO DTS.** On the 4G board the lines the AIO uses for LoRa SPI are the modem's PCM audio interface, and the modem drives the PCM clock and data-out itself. An enabled SPI4 would hold its clock and chip select against those outputs. Since LoRa has no path on the CM5 anyway, the AIO DTS does not enable SPI4, and [`tools/patch-uconsole-dtb.py`](../tools/patch-uconsole-dtb.py) disables it again in a DTB patched by an older version.
- **`aio-rails.service` runs only with the AIO present.** `aio usb on` drives the line that, on the 4G board, is the modem's STATUS output. The unit therefore carries `ConditionPathExists=/sys/bus/i2c/devices/7-0051`: the AIO's RTC on I2C7 is the one thing in that slot no other board has. With any other board the unit is skipped. The gpsd drop-in only acts when gpsd runs, which nobody enables without the AIO.

What is known about the boards in this collection, from the makers' pages and the schematics; "expected" means not tried here:

| Board | Slot lines it uses | With the AIO DTS on the CM5 |
|---|---|---|
| HackerGadgets AIO v2 | USB pair, UART (GPS, PPS on the BCM6 line), the slot I²C (RTC), the LoRa lines, four rail enables; Ethernet and USB 3.0 via the adapter | GPS, SDR, RTC, hub, RJ45 work; LoRa no path |
| HackerGadgets AIO v1 | same, but the rails are always on per HackerGadgets' guide; USB 2.0 hub, no RJ45 | expected: as v2 without the rail switching |
| HackerGadgets RJ45 / USB 3.0 board | Ethernet via the adapter's CSI routing, USB 3.0 via the adapter's connector, USB 2.0 pair; its 17-pin GPIO header is the slot's lines brought out | works |
| uCon USB expansion 3+1+1 (uHub design) | USB 2.0 pair only | expected to just work |
| ClockworkPi 4G EXT | UART, PCM, the slot I²C, modem NETLIGHT and STATUS outputs on two slot lines, power key and reset on others | UART2 from the AIO DTS is what the modem needs; untested here |

HackerGadgets' setup guide also names the AIO's GPS PPS output, BCM6 in Pi numbering, which reaches GPIO4_A2 on the CM5. A `pps-gpio` node there would give chrony a pulse-per-second reference; not tried yet.

---

## Other things the pin map settles

- **Serial console or amplifier, not both.** UART4 is the only UART with TX and RX on header pins (GPIO10/11 = HP_DET/PA_EN). Every other UART pair on the header is RTS/CTS-only or sits on the microSD lines. The upstream DTS uses UART4 TX/RX only, so the console never touched the GPS rail on GPIO1_C5 (UART4 RTS).
- **Audio.** GPIO12 (AUD_PWM0) = GPIO4_B2 has PWM14; GPIO13 has no PWM. Mono PWM audio would be possible in hardware, but mainline has no PWM-audio driver. There is no I²S in the DTS.
- **Fan.** GPIO17 (GPIO1_C2, PWM3) and GPIO22 (GPIO1_C3, PWM7) are free header pins with PWM. A MOSFET on one of them plus `pwm-fan` is the clean fan solution; the fan currently runs at a fixed 5 V from USB.
