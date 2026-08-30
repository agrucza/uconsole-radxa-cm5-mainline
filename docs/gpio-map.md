# GPIO map: CM4 socket ↔ RK3588S

The uConsole mainboard exposes a Raspberry Pi CM4-compatible socket, so its schematics and every existing uConsole overlay describe signals in **BCM GPIO numbers**. The Radxa CM5 routes those socket pins to entirely different **RK3588S** GPIO banks. This table is the translation.

## Where this comes from

The mapping is not guesswork: Radxa's own `rk3588s-radxa-cm5-rpi-cm4-io.dts` labels every socket pin via `gpio-line-names`, e.g.

```dts
&gpio1 {
	gpio-line-names =
		/* GPIO1_A0-A3 */ "", "PIN_38", "PIN_40", "PIN_12",
		/* GPIO1_B0-B3 */ "PIN_22", "PIN_21", "PIN_19", "PIN_23",
		...
};
```

Cross-referencing those physical pin numbers against the standard 40-pin header pinout gives BCM ↔ RK3588S. Every signal this project drives has been **verified against live hardware** (`/sys/kernel/debug/gpio` under both the vendor BSP and mainline). The remaining rows come from the label table and have not been individually probed.

## Bank/line notation

RK3588 GPIO lines are written `GPIOn_Xm`, where `X` is a group of 8:

| Group | Lines within bank |
|---|---|
| A | 0–7 |
| B | 8–15 |
| C | 16–23 |
| D | 24–31 |

So `GPIO1_B1` = bank 1, line 9. In device tree: `<&gpio1 RK_PB1 GPIO_ACTIVE_HIGH>`.

> **`/sys/kernel/debug/gpio` numbers differ between kernels.** The vendor BSP prints *global* numbers (`gpiochip1: GPIOs 32-63`, so GPIO1_B1 appears as `gpio-41`); mainline prints *per-chip* numbers (the same line is `gpio-9`). Same pin, different arithmetic — don't let it convince you the mapping changed.

## Signals used by this project

| BCM | Header pin | RK3588S | Device tree | Function |
|---|---|---|---|---|
| 0 | 27 (ID_SD) | GPIO1_D7 | `<&gpio1 RK_PD7>` | AXP228 I²C **SDA** (bit-banged) |
| 1 | 28 (ID_SC) | GPIO1_D6 | `<&gpio1 RK_PD6>` | AXP228 I²C **SCL** (bit-banged) |
| 2 | 3 | GPIO0_D0 | `<&gpio0 RK_PD0>` | AXP228 **IRQ**, active low |
| 8 | 24 | GPIO1_B4 | `<&gpio1 RK_PB4>` | Panel **RESX** — also the revision-detect line |
| 9 | 21 | GPIO1_B1 | `<&gpio1 RK_PB1>` | **Backlight** enable (OCP8178), active high |
| 10 | 19 | GPIO1_B2 | `<&gpio1 RK_PB2>` | **UART4 RX** (`uart4m2_xfer`) |
| 11 | 23 | GPIO1_B3 | `<&gpio1 RK_PB3>` | **UART4 TX** (`uart4m2_xfer`) |

Two of these deserve a warning:

- **Panel RESX (BCM8)** is read as an *input* at probe to identify the panel revision, then reconfigured as an output only for the original panel. Do not repurpose it.
- **UART4 RX/TX (BCM10/11)** are the only usable debug console pins on this chassis — the SoC's default `uart2` routes to Mini-PCIe and never reaches the header. See the [serial console](../README.md#serial-console) section.

## Full header mapping

| BCM | Header pin | RK3588S | Used here |
|---|---|---|---|
| 0 | 27 | GPIO1_D7 | ✅ AXP SDA |
| 1 | 28 | GPIO1_D6 | ✅ AXP SCL |
| 2 | 3 | GPIO0_D0 | ✅ AXP IRQ |
| 3 | 5 | GPIO0_C7 | free |
| 4 | 7 | GPIO1_D4 | free |
| 5 | 29 | GPIO1_C7 | free |
| 6 | 31 | GPIO4_A2 | free |
| 7 | 26 | GPIO1_B5 | free |
| 8 | 24 | GPIO1_B4 | ✅ Panel RESX |
| 9 | 21 | GPIO1_B1 | ✅ Backlight |
| 10 | 19 | GPIO1_B2 | ✅ UART4 RX |
| 11 | 23 | GPIO1_B3 | ✅ UART4 TX |
| 12 | 32 | GPIO4_B2 | free |
| 13 | 33 | GPIO4_A1 | free |
| 14 | 8 | GPIO0_B5 | uart2 TX (unreachable — Mini-PCIe) |
| 15 | 10 | GPIO0_B6 | uart2 RX (unreachable — Mini-PCIe) |
| 16 | 36 | GPIO1_A4 | free |
| 17 | 11 | GPIO1_C2 | free |
| 18 | 12 | GPIO1_A3 | free |
| 19 | 35 | *not in label table* | unknown |
| 20 | 38 | GPIO1_A1 | free |
| 21 | 40 | GPIO1_A2 | free |
| 22 | 15 | GPIO1_C3 | free |
| 23 | 16 | GPIO1_A7 | free |
| 24 | 18 | GPIO1_A6 | free |
| 25 | 22 | GPIO1_B0 | free |
| 26 | 37 | GPIO3_D0 | free |
| 27 | 13 | GPIO1_C5 | free |

"Free" means unclaimed by this device tree — the uConsole mainboard may still be using the pin for something we haven't mapped. Check `/sys/kernel/debug/gpio` on a running system before repurposing anything.

## Non-header signals worth knowing

| Signal | RK3588S | Notes |
|---|---|---|
| PCIe PERST# | GPIO3_D1 | `reset-gpios` on `pcie2x1l2`; module-side, same as Radxa's IO board |
| PCIe 3.3 V enable | GPIO1_D3 | mirrors the CM5-IO reference regulator |

## Verifying on hardware

```bash
sudo mount -t debugfs none /sys/kernel/debug
cat /sys/kernel/debug/gpio
```

Claimed lines show their consumer and electrical state:

```
gpiochip1: 32 GPIOs, parent: platform/fec20000.gpio, gpio1:
 gpio-9   (              |backlight  ) out hi
 gpio-12  (              |reset      ) in  lo ACTIVE LOW
 gpio-30  (              |scl        ) out hi
 gpio-31  (              |sda        ) out hi
```

Note `gpio-12` reading `in lo ACTIVE LOW`: physically low, which the *logical* API reports as `1` — the source of the inverted-detection trap described in [troubleshooting](troubleshooting.md#panel-revision-detection-is-inverted-from-what-youd-guess).

To check pad muxing rather than GPIO state (i.e. "is this pin even in GPIO mode?"), use the global pin number — bank × 32 + line, so GPIO1_B1 = 41:

```bash
sudo grep -iE "pin 41|backlight" /sys/kernel/debug/pinctrl/*/pinmux-pins
```
