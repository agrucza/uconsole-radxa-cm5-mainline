#!/bin/sh
# /lib/systemd/system-shutdown/axp-off.sh

[ "$1" = "poweroff" ] && i2cset -f -y 9 0x34 0x32 0xc3
