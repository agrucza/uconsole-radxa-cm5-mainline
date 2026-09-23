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

Sources: upstream's `gpio-line-names` cross-check for the RK3588S column, Radxa's CM5 pinout spreadsheet (`radxa_cm5_v2200_pinout.xlsx`, from Radxa's documentation, not included here) for the alternate functions, ClockworkPi's mainboard schematic ([github.com/clockworkpi/uConsole](https://github.com/clockworkpi/uConsole)) for the mainboard function names, and HackerGadgets' schematics of the AIO v2 edge connector and of the CM4/Radxa-CM5 adapter (rev v1.2), shared by vileer on the ClockworkPi forum on 2026-09-23 for the AIO v2 signals and the adapter's routing. "Works" means the function runs on this fork's hardware; "measured" means a continuity check on the bench (see [below](#expansion-slot-mpcie-routing)).

A word on the **header pin** column: it is the Pi position for that BCM number. On the uConsole with a CM4 or CM5 only BCM 0 to 5 and 8 to 13 actually reach the 40-pin FPC; the other positions are routed to the mPCIe expansion slot instead, which is where the AIO's signals come from. Do not expect BCM 14 to 27 on the FPC.

| BCM | Header pin | RK3588S | uConsole mainboard / AIO v2 signal | Status | Alternate functions on the CM5 |
|---|---|---|---|---|---|
| 0 | 27 | GPIO1_D7 | ID_SD → AXP228 SDA | works, this DTS (bit-banged I²C) | – |
| 1 | 28 | GPIO1_D6 | ID_SC → AXP228 SCL | works, this DTS (bit-banged I²C) | – |
| 2 | 3 | GPIO0_D0 | **PMU-IRQ (AXP228)** | works, this DTS (power button) | I2C6_SCL_M0, UART1_CTSN_M2, PWM7_IR_M0, SPI3_MISO_M2 |
| 3 | 5 | GPIO0_C7 | WL_REG_ON (unused WiFi footprint, schematic) | free | I2C6_SDA_M0, UART1_RTSN_M2, PWM6_M0, SPI0_MISO_M0 |
| 4 | 7 | GPIO1_D4 | WL_HOST_WAKE (schematic); HackerGadgets' adapter puts its RPITX connector here | free | I2S0_SDI0 |
| 5 | 29 | GPIO1_C7 | BT_REG_ON (unused WiFi footprint, schematic) | free | I2S0_SDO0, I2C4_SCL_M4, UART4_CTSN |
| 6 | 31 | GPIO4_A2 | AIO `GPIO_6` = GPS **PPS**, via mPCIe pin 38 | free; `pps-gpio` candidate | SPI0_CLK_M1, I2S1_LRCK_TX_M0, PCIE20X1_1_PERSTN_M1 |
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
| 17 | 11 | GPIO1_C2 | AIO **TP2**, a free test pad, via mPCIe pin 44 | LoRa MISO with the wire (aio-lora DTB, spi-gpio) | PWM3_IR_M2, I2C6_SDA_M1, UART3_RTSN, SPI4_CLK_M0 |
| 18 | 12 | GPIO1_A3 | AIO LoRa NSS, via mPCIe pin 18 | documented, measured on the AIO; SPI4 left disabled | SPI4_CS0_M2, PWM1_M2, I2C4_SCL_M3, UART6_CTSN_M1 |
| 19 | 35 | **NC** | AIO LoRa MISO, via mPCIe pin 20 | **not connected on the Radxa CM5** per Radxa; AIO and slot legs measured; MISO rerouted to BCM17 by the wire | – |
| 20 | 38 | GPIO1_A1 | AIO LoRa MOSI, via mPCIe pin 22 | documented, measured on the AIO | SPI4_MOSI_M2, UART6_TX_M1, I2C2_SCL_M4 |
| 21 | 40 | GPIO1_A2 | AIO LoRa SCK, via mPCIe pin 24 | documented, measured on the AIO | SPI4_CLK_M2, PWM0_M2, I2C4_SDA_M3, UART6_RTSN_M1 |
| 22 | 15 | GPIO1_C3 | – | free | PWM7_IR_M2, I2C6_SCL_M1, UART3_CTSN, SPI4_CS0_M0 |
| 23 | 16 | GPIO1_A7 | AIO **USB rail** | works, `aio usb` (never off) | SPI2_CS0_M0, PWM3_IR_M3, PCIE20X1_1_PERSTN_M2 |
| 24 | 18 | GPIO1_A6 | AIO LoRa Busy, via mPCIe pin 30 | documented, measured on the AIO | SPI2_CLK_M0 |
| 25 | 22 | GPIO1_B0 | AIO LoRa Reset, via mPCIe pin 32 | documented, measured on the AIO | SPI2_CS1_M0 |
| 26 | 37 | GPIO3_D0 | AIO LoRa IRQ (DIO1), via mPCIe pin 34 | documented, measured on the AIO | UART4_RX_M1, PWM8_M2, I2C5_SDA_M0, SPI3_CLK_M3 |
| 27 | 13 | GPIO1_C5 | AIO **GPS rail**, via mPCIe pin 36 | works, `aio gps`; path measured | UART4_RTSN, I2C2_SCL_M3, I2S0_LRCK_TX |

"Free" means unclaimed by this device tree. Check `/sys/kernel/debug/gpio` on a running system before repurposing anything.

Radxa's sheet also records each pad's reset pull as a suffix, `_d` down, `_u` up, `_z` none. Two of the four AIO rail enables are `_u`, GPIO1_B5 (SDR) and GPIO1_A7 (USB), so those two rails are on from power-up on a CM5 before any software runs; GPS (GPIO1_C5) and LoRa (GPIO1_A4) are `_d` and start off. That is why `aio` switches the SDR rail off by driving it low instead of releasing the line (see [aio-v2.md](aio-v2.md#power-rails-the-aio-tool)).

What follows from the table:

- **LoRa on the AIO v2 has no MISO path as delivered, and works with one wire.** The AIO puts MISO on finger 20 (HackerGadgets' drawing, measured), the mainboard and adapter carry it to Connector 1 position 26 (schematics, measured), and Radxa documents position 26 as NC. Finger 44, the AIO's free test pad TP2, reaches GPIO1_C2; a wire from the module's MISO pad to TP2 plus a software SPI bus makes the chip answer (2026-09-23). See [aio-v2.md](aio-v2.md#lora-no-miso-path-as-delivered).
- **The RTC is not on BCM 2/3.** The slot's I²C arrives at positions 82/80 (measured), GPIO3_D3/D2 = I2C7 `m2`, and the PCF85063A answers there. See [aio-v2.md](aio-v2.md#rtc-works-on-i2c7).
- **Serial console or amplifier, not both.** UART4 is the only UART with TX and RX on positions that reach the mainboard's audio lines (BCM10/11 = HP_DET/PA_EN). The upstream DTS uses UART4 TX/RX only, so the console never touched the GPS rail on GPIO1_C5 (UART4 RTS).
- **`uart2` is not unreachable, just not on the header.** Its `m0` pinmux sits on the BCM14/15 positions, which the uConsole routes to the mPCIe slot (measured: mPCIe 26/28 → positions 55/51). That is where the AIO's GPS listens.

## Expansion slot (mPCIe) routing

The uConsole's core port is not a CM4 socket. It is ClockworkPi's own 200-pin SO-DIMM, and a module reaches it through an adapter: ClockworkPi's CM4 adapter for a Pi, the HackerGadgets adapter for the Radxa CM5. The adapter decides which module position drives which mainboard line, and the mPCIe expansion slot carries a set of those lines that is **not** the Pi header. That is the reason the AIO's "Pi GPIO" numbers must never be read as header pins, and the reason the RTC verdict in this fork was wrong for weeks.

Sources for the table: HackerGadgets' schematics of the AIO v2 edge connector and of the CM4/Radxa-CM5 adapter (rev v1.2), shared by vileer on the ClockworkPi forum on 2026-09-23; ClockworkPi's mainboard schematic for the mPCIe pin to net mapping; Radxa's sheet for the module pins. The adapter's Connector 1 mapping is, line for line, ClockworkPi's CM4 adapter mapping; the mainboard nets appear on HackerGadgets' drawing as `DDR_GPIOnn`. "Measured" is a continuity check on this fork's hardware (mainboard plus adapter without a module on 2026-09-20 and 2026-09-23; the AIO on the bench on 2026-09-22 and 2026-09-23).

| Signal | AIO edge finger | mainboard net | SO-DIMM | Connector 1 | Radxa CM5 | Measured |
|---|---|---|---|---|---|---|
| GPS TX (Pi TXD0) | 26 | GPIO32 | 46 | 55 | GPIO0_B5, UART2 TX m0 | 26 → 55; GPS works |
| GPS RX (Pi RXD0) | 28 | GPIO33 | 48 | 51 | GPIO0_B6, UART2 RX m0 | 28 → 51; GPS works |
| GPS PPS (Pi GPIO6) | 38 | GPIO38 | 64 | 30 | GPIO4_A2 | not measured |
| GPS rail (Pi GPIO27) | 36 | GPIO37 | 60 | 48 | GPIO1_C5 | 36 → 48; rail works |
| LoRa rail (Pi GPIO16) | 42 | GPIO40 | 70 | 29 | GPIO1_A4 | 42 → 29; rail works |
| SDR rail (Pi GPIO7) | 40 | GPIO39 | 66 | 37 | GPIO1_B5 | rail works |
| USB rail (Pi GPIO23) | 48 | GPIO43 | 78 | 47 | GPIO1_A7 | rail works |
| LoRa NSS (SPI1 CE0) | 18 | GPIO28 | 28 | 49 | GPIO1_A3 | pad 15 → 18 |
| **LoRa MISO** (SPI1 MISO) | 20 | GPIO29 | 30 | 26 | **NC** | pad 13 → 20 and nowhere else; 20 → 26 and nowhere else |
| LoRa MOSI | 22 | GPIO30 | 34 | 27 | GPIO1_A1 | pad 14 → 22 |
| LoRa SCK | 24 | GPIO31 | 36 | 25 | GPIO1_A2 | pad 12 → 24 |
| LoRa Busy | 30 | GPIO34 | 52 | 45 | GPIO1_A6 | pad 10 → 30; 30 → 45 |
| LoRa Reset | 32 | GPIO35 | 54 | 41 | GPIO1_B0 | pad 4 → 32; 32 → 41 |
| LoRa IRQ (DIO1) | 34 | GPIO36 | 58 | 24 | GPIO3_D0 | pad 6 → 34 |
| **TP2**, free test pad (Pi GPIO17) | 44 | GPIO41 | 72 | 50 | GPIO1_C2 | TP2 → 44 only; 44 → 50; carries LoRa MISO with the wire |
| `Camera_GPIO` | 46 | GPIO42 | 76 | 97 (`Camera_GPIO`) | see Radxa's sheet | not measured |
| RTC SDA (Pi I2C0 SDA0) | 50 | GPIO44 | 82 | 82 | GPIO3_D3, I2C7 SDA m2 | 50 → 82; RTC answers at 0x51 |
| RTC SCL (Pi I2C0 SCL0) | 52 | GPIO45 | 84 | 80 | GPIO3_D2, I2C7 SCL m2 | 52 → 80; RTC answers at 0x51 |
| AXP SDA (anchor) | – | GPIO0 | 3 | 36 | GPIO1_D7 | SO-DIMM 3 → 36; AXP works |

The remaining fingers carry no GPIO: 5 V on the even fingers 2 to 10 (they beep to each other, handy for orientation), the two USB 2.0 pairs on 7/9 (SDR) and 13/15 (hub), 3.3 V, ground and the speaker lines, and on the CSI positions 23 to 49 the Ethernet LEDs and pairs the adapter routes there for the RJ45.

**The adapter's fan header** is on the Radxa module's third connector: PWM on pin 18 = GPIO3_D5, hardware PWM11 in its `m3` pinmux; tacho on pin 38 = GPIO4_A4. Both from HackerGadgets' drawing and Radxa's sheet, not measured.

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
