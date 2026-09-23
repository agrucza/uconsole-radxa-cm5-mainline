#!/usr/bin/env python3
"""Bit-bang SPI probe for the AIO v2 SX1262 on the Radxa CM5, independent of SPI4/spidev.

This is the test that established why LoRa cannot work on a Radxa CM5: MISO
(AIO edge finger 20, Connector 1 position 26) is not connected on the module, so the chip's
GetStatus reply never arrives and MISO follows whatever bias you apply.
Kept as a diagnostic; see docs/aio-v2.md for the result and the options.

Lines on gpiochip1: 0 = GPIO1_A0 MISO, 1 = GPIO1_A1 MOSI, 2 = GPIO1_A2 CLK, 3 = GPIO1_A3 CS.
Reset = line 8 (GPIO1_B0), Busy = line 6 (GPIO1_A6).
The LoRa rail must be on first:  sudo aio lora on
Needs the libgpiod v2 Python bindings (python3-libgpiod).
"""
import time
import gpiod
from gpiod.line import Direction, Value, Bias

MISO, MOSI, CLK, CS, BUSY, RST = 0, 1, 2, 3, 6, 8
req = gpiod.request_lines("/dev/gpiochip1", consumer="sx1262-bb", config={
    MISO: gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP),
    BUSY: gpiod.LineSettings(direction=Direction.INPUT),
    MOSI: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.INACTIVE),
    CLK:  gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.INACTIVE),
    CS:   gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE),
    RST:  gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE),
})


def xfer(byte):
    r = 0
    for i in range(7, -1, -1):
        req.set_value(MOSI, Value.ACTIVE if (byte >> i) & 1 else Value.INACTIVE)
        req.set_value(CLK, Value.ACTIVE)
        r = (r << 1) | (1 if req.get_value(MISO) == Value.ACTIVE else 0)
        req.set_value(CLK, Value.INACTIVE)
    return r


# reset pulse
req.set_value(RST, Value.INACTIVE)
time.sleep(0.01)
req.set_value(RST, Value.ACTIVE)
time.sleep(0.05)
print("Busy after reset:", req.get_value(BUSY))
print("MISO idle (CS high, pull-up):", req.get_value(MISO))
req.set_value(CS, Value.INACTIVE)
time.sleep(0.001)
print("MISO with CS low:", req.get_value(MISO))
for _ in range(3):
    req.set_value(CS, Value.INACTIVE)
    a, b = xfer(0xC0), xfer(0x00)      # GetStatus
    req.set_value(CS, Value.ACTIVE)
    print(f"GetStatus -> {a:#04x} {b:#04x}")
    time.sleep(0.1)

# bias test: with a pull-down, does MISO follow the bias (floating / not
# connected) or does the chip drive it?
req.release()
req = gpiod.request_lines("/dev/gpiochip1", consumer="sx1262-bb", config={
    MISO: gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_DOWN),
    CS:   gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.INACTIVE)})
time.sleep(0.001)
print("MISO with CS low, pull-down:", req.get_value(MISO), "(follows bias = floating/not connected)")
