#!/bin/bash
# Reproducible mainline-7.1 kernel build for ClockworkPi uConsole (Radxa CM5)
# Regenerates .config from defconfig + fragment, builds Image/modules/dtbs.
# Safe to run after make distclean.
set -euo pipefail

KDIR="${KDIR:-$HOME/uconsole/sources/linux-7.1}"
STAGING="${STAGING:-$HOME/uconsole/staging/modules-7.1}"
FRAGMENT="$HOME/uconsole/configs/uconsole-7.1.config"

export ARCH=arm64
# Cross-compile only when building on a non-aarch64 host (e.g. x86_64 PC).
# On the uConsole itself this must stay unset for a native build.
if [ "$(uname -m)" != "aarch64" ]; then
	export CROSS_COMPILE=aarch64-linux-gnu-
fi

mkdir -p "$(dirname "$FRAGMENT")"

# ---------------------------------------------------------------
# Config fragment — consolidated from the full bring-up history.
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
# ---- HDMI (debug/secondary output) ----
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
# ---- WiFi: RealTek RTW88 USB dongles ----
CONFIG_WLAN=y
CONFIG_WLAN_VENDOR_REALTEK=y
CONFIG_RTW88=m
CONFIG_RTW88_USB=m
CONFIG_RTW88_8821CU=m
CONFIG_RTW88_8822BU=m
CONFIG_RTW88_8822CU=m
CONFIG_RTW88_8723DU=m
# ---- Debug tooling ----
CONFIG_NETCONSOLE=m
EOF

cd "$KDIR"

echo "== Sanity: our source additions survived? =="
test -f drivers/gpu/drm/panel/panel-cwu50.c || { echo "MISSING panel-cwu50.c"; exit 1; }
test -f arch/arm64/boot/dts/rockchip/rk3588s-radxa-cm5-uconsole.dts || { echo "MISSING uconsole DTS"; exit 1; }
grep -q CWU50 drivers/gpu/drm/panel/Kconfig   || { echo "MISSING Kconfig entry"; exit 1; }
grep -q cwu50 drivers/gpu/drm/panel/Makefile  || { echo "MISSING Makefile entry"; exit 1; }
grep -q uconsole arch/arm64/boot/dts/rockchip/Makefile || { echo "MISSING dtb Makefile entry"; exit 1; }
echo "   all present."

echo "== Config: defconfig + fragment =="
test -f .config || make defconfig
./scripts/kconfig/merge_config.sh .config "$FRAGMENT"

echo "== Verify critical symbols =="
for sym in DRM_PANEL_CLOCKWORKPI_CWU50 ROCKCHIP_DW_MIPI_DSI2 \
           PHY_ROCKCHIP_SAMSUNG_DCPHY FRAMEBUFFER_CONSOLE_ROTATION \
           BATTERY_AXP20X DWMAC_ROCKCHIP; do
	grep -q "^CONFIG_${sym}=y" .config || { echo "FAILED: $sym not =y"; exit 1; }
done
grep -q "^CONFIG_NETCONSOLE=m" .config || { echo "FAILED: NETCONSOLE not =m"; exit 1; }
echo "   all good."

echo "== Build =="
make -j"$(nproc)" Image modules dtbs

echo "== Stage modules =="
rm -rf "$STAGING"
make INSTALL_MOD_PATH="$STAGING" modules_install

KREL=$(cat include/config/kernel.release)
echo ""
echo "== DONE. Kernel: $KREL =="
echo "Deploy:"
echo "  scp arch/arm64/boot/Image \$DEV:/tmp/Image-7.1"
echo "  scp arch/arm64/boot/dts/rockchip/rk3588s-radxa-cm5-uconsole.dtb \$DEV:/tmp/"
echo "  scp drivers/net/netconsole.ko \$DEV:/tmp/"
echo "  rsync -a $STAGING/lib/modules/$KREL \$DEV:/tmp/mods/"
echo "Or:"
echo "  sudo mv /boot/Image-7.1 /boot/Image-7.1-old"
echo "  sudo cp arch/arm64/boot/Image /boot/Image-7.1"
echo "  sudo mv /boot/dtb-7.1/* /boot/dtb-7.1-old/"
echo "  sudo cp arch/arm64/boot/dts/rockchip/rk3588s-radxa-cm5-uconsole.dtb /boot/dtb-7.1/"
echo "  # sudo cp drivers/net/netconsole.ko \$DEV:/tmp/"
echo "  sudo rsync -a --no-o --no-g $STAGING/lib/modules/$KREL /lib/modules/"
