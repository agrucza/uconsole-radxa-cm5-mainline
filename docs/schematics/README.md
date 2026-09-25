# Vendor schematics

Two drawings by HackerGadgets, shared by vileer (HackerGadgets) on the ClockworkPi forum on
2026-09-23 and included here with their permission. They are the source for the expansion-slot
routing in [gpio-map.md](../gpio-map.md#expansion-slot-mpcie-routing) and for the LoRa, fan and
PPS sections of [aio-v2.md](../aio-v2.md). Copyright HackerGadgets; not covered by this
repository's licence, do not reuse outside this documentation without asking them.

| file | what it shows |
|---|---|
| [`hackergadgets-aio-v2-mpcie-connector.png`](hackergadgets-aio-v2-mpcie-connector.png) | AIO v2 edge connector `J1 uConsoleEXT`: every mPCIe finger with its signal (LoRa SPI, GPS UART, rails, RTC I²C, the free test pad TP2 on finger 44, USB and Ethernet pairs) |
| [`hackergadgets-cm4-radxa-cm5-adapter-v1.2.jpg`](hackergadgets-cm4-radxa-cm5-adapter-v1.2.jpg) | "uConsole CM4/Radxa-CM5 Adapter Board" rev v1.2 (2025-09-12), page 2/2: the module's three connectors against the SO-DIMM (`DDR_GPIOnn` = mainboard nets), the Ethernet transformer, the fan header on connector 3 (pins 218/238) |

The other two sources of the pin map are not included: ClockworkPi's mainboard schematic is at
[github.com/clockworkpi/uConsole](https://github.com/clockworkpi/uConsole), Radxa's CM5 pinout
spreadsheet (`radxa_cm5_v2200_pinout.xlsx`) is in Radxa's documentation.
