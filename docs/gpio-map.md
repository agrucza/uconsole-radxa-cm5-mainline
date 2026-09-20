# GPIO map: CM4 socket ↔ RK3588S

The uConsole was designed around the Raspberry Pi CM4, so its schematics, HackerGadgets' documentation and every existing uConsole overlay describe signals in **BCM GPIO numbers**: the GPIO numbering of the Pi's Broadcom SoC, the "GPIO19" a Pi user types. The Radxa CM5 sits in the same place, through an adapter, and routes those positions to entirely different **RK3588S** GPIO pins. This table is the translation.

Four ways of naming one wire appear in this document:

| Name | What it counts | Example |
|---|---|---|
| **BCM** | GPIO number inside the Pi's SoC; what Pi software and HackerGadgets mean | BCM19 = SPI1 MISO on a Pi |
| **Header pin** | physical position 1 to 40 on the Pi header, the uConsole's 40-pin FPC | header pin 35 carries BCM19 on a Pi |
| **RK3588S** | the Radxa module's own pin name, bank, group, line | GPIO1_A4 |
| **Connector 1 position** | pin number on the module's first 100-pin connector, the CM4's numbering, used for bench measurements | position 26 |

Radxa labels each connector position with the BCM name a CM4 would have there, which makes BCM the common key between the Pi world, Radxa's sheet and the uConsole.

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

Sources: upstream's `gpio-line-names` cross-check for the RK3588S column, Radxa's CM5 pinout spreadsheet (`radxa_cm5_v2200_pinout.xlsx`, from Radxa's documentation, not included here) for the alternate functions, ClockworkPi's mainboard schematic ([github.com/clockworkpi/uConsole](https://github.com/clockworkpi/uConsole)) for the mainboard function names, and HackerGadgets' Pi pin list for the AIO v2 signals. "Works" means the function runs on this fork's hardware; "measured" means a continuity check on the bench (see [below](#expansion-slot-mpcie-routing)).

A word on the **header pin** column: it is the Pi position for that BCM number. On the uConsole with a CM4 or CM5 only BCM 0 to 5 and 8 to 13 actually reach the 40-pin FPC; the other positions are routed to the mPCIe expansion slot instead, which is where the AIO's signals come from. Do not expect BCM 14 to 27 on the FPC.

| BCM | Header pin | RK3588S | uConsole mainboard / AIO v2 signal | Status | Alternate functions on the CM5 |
|---|---|---|---|---|---|
| 0 | 27 | GPIO1_D7 | ID_SD → AXP228 SDA | works, this DTS (bit-banged I²C) | – |
| 1 | 28 | GPIO1_D6 | ID_SC → AXP228 SCL | works, this DTS (bit-banged I²C) | – |
| 2 | 3 | GPIO0_D0 | **PMU-IRQ (AXP228)** | works, this DTS (power button) | I2C6_SCL_M0, UART1_CTSN_M2, PWM7_IR_M0, SPI3_MISO_M2 |
| 3 | 5 | GPIO0_C7 | WL_REG_ON (unused WiFi footprint, schematic) | free | I2C6_SDA_M0, UART1_RTSN_M2, PWM6_M0, SPI0_MISO_M0 |
| 4 | 7 | GPIO1_D4 | WL_HOST_WAKE (schematic); HackerGadgets' adapter puts its RPITX connector here | free | I2S0_SDI0 |
| 5 | 29 | GPIO1_C7 | BT_REG_ON (unused WiFi footprint, schematic) | free | I2S0_SDO0, I2C4_SCL_M4, UART4_CTSN |
| 6 | 31 | GPIO4_A2 | – | free | SPI0_CLK_M1, I2S1_LRCK_TX_M0, PCIE20X1_1_PERSTN_M1 |
| 7 | 26 | GPIO1_B5 | AIO **SDR rail** | works, `aio sdr` | UART7_TX_M2, SPI0_CS1_M2 |
| 8 | 24 | GPIO1_B4 | LCD_RESET | works, panel RESX / revision detect | UART7_RX_M2, SPI0_CS0_M2 |
| 9 | 21 | GPIO1_B1 | BL_CTRL (OCP8178) | works, backlight | SPI0_MISO_M2 |
| 10 | 19 | GPIO1_B2 | HP_DET | works, UART4 RX (console) | UART4_RX_M2, SPI0_MOSI_M2 |
| 11 | 23 | GPIO1_B3 | PA_EN (AW8110 amplifier enable) | works, UART4 TX (console); the AIO DTB hogs it low instead | UART4_TX_M2, SPI0_CLK_M2, SATA0_ACT_LED_M1 |
| 12 | 32 | GPIO4_B2 | AUD_PWM0 (schematic) | free | PWM14_M1, I2C7_SCL_M3, SPI0_CS0_M1, UART8_RTSN_M0, CAN1_RX_M1 |
| 13 | 33 | GPIO4_A1 | AUD_PWM1 (schematic) | free | SPI0_MOSI_M1, I2S1_SCLK_TX_M0, UART9_CTSN_M1 |
| 14 | 8 | GPIO0_B5 | AIO GPS TX, via mPCIe pin 26 | works, UART2 TX (`uart2m0`); path measured | UART2_TX_M0, I2C1_SCL_M0, I2S1_MCLK_M1 |
| 15 | 10 | GPIO0_B6 | AIO GPS RX, via mPCIe pin 28 | works, UART2 RX (`uart2m0`); path measured | UART2_RX_M0, I2C1_SDA_M0 |
| 16 | 36 | GPIO1_A4 | AIO **LoRa rail** | works, `aio lora` | SPI2_MISO_M0 |
| 17 | 11 | GPIO1_C2 | – | free | PWM3_IR_M2, I2C6_SDA_M1, UART3_RTSN, SPI4_CLK_M0 |
| 18 | 12 | GPIO1_A3 | AIO LoRa CS (HackerGadgets' Pi numbering) | AIO DTB: SPI4 CS0 (`spi4m2`); LoRa not working | SPI4_CS0_M2, PWM1_M2, I2C4_SCL_M3, UART6_CTSN_M1 |
| 19 | 35 | **NC** | AIO LoRa MISO, via mPCIe pin 20 | **not connected on the Radxa CM5** per Radxa; path to position 26 measured | – |
| 20 | 38 | GPIO1_A1 | AIO LoRa MOSI (HackerGadgets' Pi numbering) | AIO DTB: SPI4 MOSI (`spi4m2`); LoRa not working | SPI4_MOSI_M2, UART6_TX_M1, I2C2_SCL_M4 |
| 21 | 40 | GPIO1_A2 | AIO LoRa CLK (HackerGadgets' Pi numbering) | AIO DTB: SPI4 CLK (`spi4m2`); LoRa not working | SPI4_CLK_M2, PWM0_M2, I2C4_SDA_M3, UART6_RTSN_M1 |
| 22 | 15 | GPIO1_C3 | – | free | PWM7_IR_M2, I2C6_SCL_M1, UART3_CTSN, SPI4_CS0_M0 |
| 23 | 16 | GPIO1_A7 | AIO **USB rail** | works, `aio usb` (never off) | SPI2_CS0_M0, PWM3_IR_M3, PCIE20X1_1_PERSTN_M2 |
| 24 | 18 | GPIO1_A6 | AIO LoRa Busy (HackerGadgets' Pi numbering) | LoRa not working | SPI2_CLK_M0 |
| 25 | 22 | GPIO1_B0 | AIO LoRa Reset (HackerGadgets' Pi numbering) | LoRa not working | SPI2_CS1_M0 |
| 26 | 37 | GPIO3_D0 | AIO LoRa IRQ, DIO1 (HackerGadgets' Pi numbering) | LoRa not working | UART4_RX_M1, PWM8_M2, I2C5_SDA_M0, SPI3_CLK_M3 |
| 27 | 13 | GPIO1_C5 | AIO **GPS rail**, via mPCIe pin 36 | works, `aio gps`; path measured | UART4_RTSN, I2C2_SCL_M3, I2S0_LRCK_TX |

"Free" means unclaimed by this device tree. Check `/sys/kernel/debug/gpio` on a running system before repurposing anything.

Radxa's sheet also records each pad's reset pull as a suffix, `_d` down, `_u` up, `_z` none. Two of the four AIO rail enables are `_u`, GPIO1_B5 (SDR) and GPIO1_A7 (USB), so those two rails are on from power-up on a CM5 before any software runs; GPS (GPIO1_C5) and LoRa (GPIO1_A4) are `_d` and start off. That is why `aio` switches the SDR rail off by driving it low instead of releasing the line (see [aio-v2.md](aio-v2.md#power-rails-the-aio-tool)).

What follows from the table:

- **LoRa on the AIO v2 is not available and probably has no path.** The line HackerGadgets use for MISO arrives at Connector 1 position 26 (measured), and Radxa documents position 26 as NC. See [aio-v2.md](aio-v2.md#lora-not-available-probably-no-path).
- **The RTC is not on BCM 2/3.** The slot's I²C arrives at positions 82/80 (measured), GPIO3_D3/D2 = I2C7 `m2`, and the PCF85063A answers there. See [aio-v2.md](aio-v2.md#rtc-works-on-i2c7).
- **Serial console or amplifier, not both.** UART4 is the only UART with TX and RX on positions that reach the mainboard's audio lines (BCM10/11 = HP_DET/PA_EN). The upstream DTS uses UART4 TX/RX only, so the console never touched the GPS rail on GPIO1_C5 (UART4 RTS).
- **`uart2` is not unreachable, just not on the header.** Its `m0` pinmux sits on the BCM14/15 positions, which the uConsole routes to the mPCIe slot (measured: mPCIe 26/28 → positions 55/51). That is where the AIO's GPS listens.

## Expansion slot (mPCIe) routing

The uConsole's core port is not a CM4 socket. It is ClockworkPi's own 200-pin SO-DIMM, and a module reaches it through an adapter: ClockworkPi's CM4 adapter for a Pi, the HackerGadgets adapter for the Radxa CM5. The adapter decides which module position drives which mainboard line, and the mPCIe expansion slot carries a set of those lines that is **not** the Pi header. That is the reason the AIO's "Pi GPIO" numbers must never be read as header pins, and the reason the RTC verdict in this fork was wrong for weeks.

Rather than transcribe the schematics, this section keeps to what was measured on 2026-09-20 (spare mainboard, spare HackerGadgets adapter, no module, unpowered, continuity from the mPCIe socket's solder tails or the SO-DIMM edge to Connector 1) and to what runs:

| Signal | BCM | mPCIe pin | Connector 1 | Radxa CM5 | Evidence |
|---|---|---|---|---|---|
| GPS TX | 14 | 26 | 55 | GPIO0_B5, UART2 TX m0 | measured 26 → 55; GPS works |
| GPS RX | 15 | 28 | 51 | GPIO0_B6, UART2 RX m0 | measured 28 → 51; GPS works |
| GPS rail | 27 | 36 | 48 | GPIO1_C5 | measured 36 → 48; rail works |
| LoRa MISO | 19 | 20 | 26 | **NC** per Radxa | measured 20 → 26 and nowhere else |
| RTC SDA | SDA0 | 50 | 82 | GPIO3_D3, I2C7 SDA m2 | measured 50 → 82; RTC answers at 0x51 |
| RTC SCL | SCL0 | 52 | 80 | GPIO3_D2, I2C7 SCL m2 | measured 52 → 80; RTC answers at 0x51 |
| AXP SDA | ID_SD | – | 36 | GPIO1_D7 | measured SO-DIMM 3 → 36; AXP works |
| LoRa rail | 16 | not measured | 29 | GPIO1_A4 | rail works |
| SDR rail | 7 | not measured | 37 | GPIO1_B5 | rail works |
| USB rail | 23 | not measured | 47 | GPIO1_A7 | rail works |

Connector 1 positions and RK3588S names are from Radxa's sheet; mPCIe pin numbers from ClockworkPi's mainboard schematic, confirmed by the beeps listed. The remaining unmeasured stretch is the AIO board itself, which module pad goes to which mPCIe finger; it will be checked when the AIO can come out of the running unit.

### Measuring it yourself

Everything unpowered, no battery, no module. Connector 1 is the module's first 100-pin connector ("Connector 1" / U33-A on Radxa's IO board): two rows of 50 at 0.4 mm, odd numbers in one row, even in the other, position n = pin (n+1)/2 of the odd row or n/2 of the even row, counted from the pin-1 end. The mPCIe socket's 52 solder tails exit the back of its housing; pin 1 is marked, even pins 2 to 10 are all 5 V and beep to each other, which fixes row and direction. SO-DIMM 3 to position 36 is a good first anchor: it is the AXP's SDA line and must beep.

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
