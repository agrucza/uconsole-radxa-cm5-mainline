#!/bin/bash
# Reproducible mainline kernel build for ClockworkPi uConsole (Radxa CM5)
#
# Regenerates .config from defconfig + fragment, builds Image/modules/dtbs.
# Works natively on the uConsole and cross-compiled from an x86_64 host.
# Safe to run after make distclean.
#
# Usage:
#   ./build-uconsole-kernel.sh              # build $KVER from default paths
#   KVER=7.2 ./build-uconsole-kernel.sh     # build a different version
#   FORCE_DEFCONFIG=1 ./build-uconsole-kernel.sh    # discard existing .config
#   DTBS_ONLY=1 ./build-uconsole-kernel.sh          # only `make dtbs` (seconds), for DTS edits
#
# Device trees built: rk3588s-radxa-cm5-uconsole.dtb (base) and, if its source
# is present in the tree, rk3588s-radxa-cm5-uconsole-aio.dtb (HackerGadgets
# AIO v2 variant, see docs/aio-v2.md).
set -euo pipefail

# Single knob for version bumps — everything else derives from it.
KVER="${KVER:-7.2}"
BASE="${BASE:-$HOME/Work}"

KDIR="${KDIR:-$BASE/linux-$KVER}"
STAGING="${STAGING:-$BASE/staging/modules-$KVER}"
FRAGMENT="${FRAGMENT:-$BASE/configs/uconsole-$KVER.config}"

export ARCH=arm64
# Cross-compile only when building on a non-aarch64 host (e.g. x86_64 PC).
# On the uConsole itself this must stay unset for a native build.
if [ "$(uname -m)" != "aarch64" ]; then
	export CROSS_COMPILE=aarch64-linux-gnu-
fi

mkdir -p "$(dirname "$FRAGMENT")"

# ---------------------------------------------------------------
# Config fragment — consolidated from the full bring-up history.
# This file, not .config, is the source of truth.
# ---------------------------------------------------------------
cat > "$FRAGMENT" << 'EOF'
# ---- Display chain (all =y: no initramfs, fbcon at boot) ----
CONFIG_DRM=y
CONFIG_DRM_ROCKCHIP=y
CONFIG_ROCKCHIP_VOP2=y
CONFIG_ROCKCHIP_DW_MIPI_DSI2=y
CONFIG_PHY_ROCKCHIP_SAMSUNG_DCPHY=y
CONFIG_DRM_PANEL_CLOCKWORKPI_CWU50=y
CONFIG_DRM_FBDEV_EMULATION=y
CONFIG_FRAMEBUFFER_CONSOLE=y
# fbcon rotation: required for panel orientation to work at console
CONFIG_FRAMEBUFFER_CONSOLE_ROTATION=y
# ---- HDMI (secondary output) ----
CONFIG_ROCKCHIP_DW_HDMI_QP=y
CONFIG_PHY_ROCKCHIP_SAMSUNG_HDPTX=y
# ---- Storage (rootfs-critical, must be built-in) ----
CONFIG_MMC_DW=y
CONFIG_MMC_DW_ROCKCHIP=y
CONFIG_MMC_SDHCI_OF_DWCMSHC=y
# ---- Ethernet (built-in: SSH from the moment boot completes) ----
CONFIG_STMMAC_ETH=y
CONFIG_STMMAC_PLATFORM=y
CONFIG_DWMAC_ROCKCHIP=y
# ---- AXP228 PMU (mainboard, bit-banged I2C) ----
CONFIG_I2C_GPIO=y
CONFIG_MFD_AXP20X=y
CONFIG_MFD_AXP20X_I2C=y
CONFIG_REGULATOR_AXP20X=y
CONFIG_AXP20X_POWER=y
# IIO ADC: dependency of BATTERY_AXP20X
CONFIG_IIO=y
CONFIG_AXP20X_ADC=y
CONFIG_BATTERY_AXP20X=y
CONFIG_CHARGER_AXP20X=y
# Power button: the uConsole's button is on the AXP228 PEK pin, not the
# CM5 module's RK806. Without this the MFD creates an orphaned
# "axp221-pek" platform device and short presses do nothing.
CONFIG_INPUT_MISC=y
CONFIG_INPUT_AXP20X_PEK=y
# ---- Backlight ----
CONFIG_BACKLIGHT_CLASS_DEVICE=y
CONFIG_BACKLIGHT_GPIO=y
# OCP8178 one-wire dimming (kernel/ocp8178_bl.c); the AIO DTS requires it
CONFIG_BACKLIGHT_OCP8178=y
# ---- Serial console (UART4 m2 @ 1.5 Mbps) ----
CONFIG_SERIAL_8250=y
CONFIG_SERIAL_8250_CONSOLE=y
CONFIG_SERIAL_8250_DW=y
# ---- USB gadget (future CDC-ACM debug) ----
CONFIG_USB_GADGET=y
CONFIG_USB_CONFIGFS=y
CONFIG_USB_CONFIGFS_ACM=y
# ---- PCIe / NVMe (HackerGadgets NVMe board) ----
# PHY must be built-in: the =y host driver probes before modules load
# and there is no initramfs to rescue a modular PHY.
CONFIG_PCI=y
CONFIG_PCIEPORTBUS=y
CONFIG_PCIE_ROCKCHIP_DW=y
CONFIG_PCIE_ROCKCHIP_DW_HOST=y
CONFIG_PHY_ROCKCHIP_NANENG_COMBO_PHY=y
CONFIG_BLK_DEV_NVME=y
# ---- WiFi: RealTek RTW88 USB dongles (trim to your hardware) ----
CONFIG_WLAN=y
CONFIG_WLAN_VENDOR_REALTEK=y
CONFIG_RTW88=m
CONFIG_RTW88_USB=m
CONFIG_RTW88_8821CU=m
CONFIG_RTW88_8822BU=m
CONFIG_RTW88_8822CU=m
CONFIG_RTW88_8723DU=m
# RTL8812AU (tested: Skyworth module on the internal USB header) — needs
# firmware rtw88/rtw8812a_fw.bin (Debian: firmware-realtek)
CONFIG_RTW88_8812A=m
CONFIG_RTW88_8812AU=m
# ---- Debug tooling ----
CONFIG_NETCONSOLE=m
EOF

cd "$KDIR"

echo "== Building kernel $KVER in $KDIR =="

echo "== Sanity: our source additions present? =="
test -f drivers/gpu/drm/panel/panel-cwu50.c || { echo "MISSING panel-cwu50.c"; exit 1; }
test -f arch/arm64/boot/dts/rockchip/rk3588s-radxa-cm5-uconsole.dts || { echo "MISSING uconsole DTS"; exit 1; }
grep -q CWU50 drivers/gpu/drm/panel/Kconfig   || { echo "MISSING Kconfig entry"; exit 1; }
grep -q cwu50 drivers/gpu/drm/panel/Makefile  || { echo "MISSING Makefile entry"; exit 1; }
grep -q uconsole arch/arm64/boot/dts/rockchip/Makefile || { echo "MISSING dtb Makefile entry"; exit 1; }
DTB_DIR="arch/arm64/boot/dts/rockchip"
DTBS="$DTB_DIR/rk3588s-radxa-cm5-uconsole.dtb"
HAVE_OCP8178=
if [ -f drivers/video/backlight/ocp8178_bl.c ]; then
	grep -q BACKLIGHT_OCP8178 drivers/video/backlight/Kconfig  || { echo "MISSING Kconfig entry for ocp8178_bl"; exit 1; }
	grep -q ocp8178_bl drivers/video/backlight/Makefile         || { echo "MISSING Makefile entry for ocp8178_bl"; exit 1; }
	HAVE_OCP8178=1
	echo "   OCP8178 backlight driver present."
fi
if [ -f "$DTB_DIR/rk3588s-radxa-cm5-uconsole-aio.dts" ]; then
	grep -q uconsole-aio "$DTB_DIR/Makefile" || { echo "MISSING dtb Makefile entry for uconsole-aio"; exit 1; }
	[ -n "$HAVE_OCP8178" ] || { echo "the AIO DTS uses the OCP8178 backlight: add drivers/video/backlight/ocp8178_bl.c (README step 2)"; exit 1; }
	DTBS="$DTBS $DTB_DIR/rk3588s-radxa-cm5-uconsole-aio.dtb"
	echo "   AIO v2 DTS present, will be built too."
else
	echo "   (no rk3588s-radxa-cm5-uconsole-aio.dts in the tree: base DTB only)"
fi
echo "   all present."

if [ -n "${DTBS_ONLY:-}" ]; then
	echo "== DTBS_ONLY: building device trees only =="
	test -f .config || { echo "no .config yet: run a full build first"; exit 1; }
	make dtbs
	echo
	echo "== DONE. Copy the DTB(s) next to the kernel they belong to: =="
	for d in $DTBS; do echo "  sudo cp $d /boot/dtb-$KVER/"; done
	exit 0
fi

echo "== Config =="
if [ -n "${FORCE_DEFCONFIG:-}" ]; then
	echo "   FORCE_DEFCONFIG set — regenerating from defconfig."
	make defconfig
elif [ -f .config ]; then
	echo "   NOTE: reusing the existing .config as the merge base."
	echo "         Any manual tweaks in it are preserved, but the build is"
	echo "         then NOT reproducible from scratch. Run with"
	echo "         FORCE_DEFCONFIG=1 to start clean from defconfig."
	# After a version bump an inherited .config needs resolving first.
	make olddefconfig
else
	make defconfig
fi

./scripts/kconfig/merge_config.sh .config "$FRAGMENT"

echo "== Verify critical symbols =="
# Each of these has failed silently at least once during bring-up.
for sym in DRM_PANEL_CLOCKWORKPI_CWU50 ROCKCHIP_DW_MIPI_DSI2 \
           PHY_ROCKCHIP_SAMSUNG_DCPHY FRAMEBUFFER_CONSOLE_ROTATION \
           BATTERY_AXP20X INPUT_AXP20X_PEK DWMAC_ROCKCHIP \
           PCIE_ROCKCHIP_DW_HOST PHY_ROCKCHIP_NANENG_COMBO_PHY; do
	grep -q "^CONFIG_${sym}=y" .config || { echo "FAILED: $sym not =y"; exit 1; }
done
grep -q "^CONFIG_NETCONSOLE=m" .config || { echo "FAILED: NETCONSOLE not =m"; exit 1; }
if [ -n "$HAVE_OCP8178" ]; then
	grep -q "^CONFIG_BACKLIGHT_OCP8178=y" .config || { echo "FAILED: BACKLIGHT_OCP8178 not =y"; exit 1; }
fi
echo "   all good."

echo "== Build =="
make -j"$(nproc)" Image modules dtbs

echo "== Stage modules =="
rm -rf "$STAGING"
make INSTALL_MOD_PATH="$STAGING" modules_install

KREL=$(cat include/config/kernel.release)

cat << DEPLOY

== DONE. Kernel: $KREL ==

Deploy ALL THREE artifacts together — a stale DTB fails silently.

--- Native (building on the uConsole) ---
  sudo mv /boot/Image-$KVER /boot/Image-$KVER-old
  sudo cp arch/arm64/boot/Image /boot/Image-$KVER
  sudo mkdir -p /boot/dtb-$KVER-old
  sudo mv /boot/dtb-$KVER/* /boot/dtb-$KVER-old/ 2>/dev/null || true
  sudo cp $DTBS /boot/dtb-$KVER/
  sudo rsync -a --no-o --no-g $STAGING/lib/modules/$KREL /lib/modules/

--- Cross (building on a PC, \$DEV=user@uconsole) ---
  scp arch/arm64/boot/Image \$DEV:/tmp/Image-$KVER
  scp $DTBS \$DEV:/tmp/
  scp drivers/net/netconsole.ko \$DEV:/tmp/
  rsync -a $STAGING/lib/modules/$KREL \$DEV:/tmp/mods/

--- After rebooting, verify you are running what you just built ---
  uname -r                                                         # $KREL
  tr -d '\\0' < /sys/firmware/devicetree/base/pcie@fe190000/status  # okay
  sudo dmesg | grep "panel:"                                       # TXW500170B0-BL

DEPLOY
