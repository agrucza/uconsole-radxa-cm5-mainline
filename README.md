# uConsole + Radxa CM5 on mainline Linux 7.1

Mainline kernel support for the [ClockworkPi uConsole](https://www.clockworkpi.com/uconsole) running a **Radxa CM5** (Rockchip RK3588S) module — including the **new December-2025 LCD revision (TXW500170B0-BL)** that the older community drivers render as garbage.

No BSP tree, no vendor kernel. Just mainline `v7.1` plus one panel driver and one device tree.

![glmark2 2611 on Mali-G610](docs/screenshot.jpg)

---

## Status

| Feature | State |
|---|---|
| LCD — TXW500170B0-BL (new, Dec 2025+) | ✅ works |
| LCD — TXW500170B0 (original) | ⚠️ auto-detected, code path present, **untested** — reports welcome |
| GPU — Mali-G610 (panthor + Mesa panfrost) | ✅ GLES accelerated, glmark2 ≈ 2611 |
| Wayland — sway, labwc | ✅ works |
| Internal keyboard + trackball | ✅ works |
| Ethernet (RTL8211F) | ✅ works |
| eMMC + microSD | ✅ works |
| NVMe (HackerGadgets NVMe board, PCIe) | ✅ Gen2 x1 link, works |
| Battery charging | ✅ works |
| Poweroff / reboot | ✅ works (with included shutdown hook) |
| USB (internal hub, external ports) | ✅ works |
| HDMI | ✅ under Wayland (hotplug included); ⚠️ boot console needs it connected at power-on |
| Backlight brightness | ⚠️ on/off only — no dimming steps yet |
| Orange charge LED | ❌ stays dark (charging itself is fine) |
| WiFi | via USB dongle (RTW88 configs included); CM5 has no onboard radio |
| Audio | ❌ not addressed here (no analog DAC on Radxa CM5) |

**Known workaround required:** the first DSI enable at boot wedges the controller (see [Troubleshooting](docs/troubleshooting.md)). A one-shot systemd service cycles the display at boot and fixes it. This looks like a genuine mainline `dw-mipi-dsi2` bug, not something specific to this board.

---

## Hardware this was built and tested on

- ClockworkPi uConsole (2026 revision, **TXW500170B0-BL** panel — check the sticker on the back of the LCD)
- Radxa CM5 (RK3588S), 8 GB / 64 GB eMMC
- HackerGadgets Radxa CM5 adapter board
- HackerGadgets NVMe board (Samsung SM981 SSD)
- Arch Linux ARM userspace, Mesa 26.1.4, panthor 1.8.0, CSF firmware v1.5.0

If your hardware differs — original panel, no NVMe board, a different adapter — the device tree may need edits. The panel revision is detected at runtime, so **both panel types should work**; the NVMe/PCIe nodes are harmless if the board is absent.

---

## ⚠️ Read this before you deploy anything

**Keep a working boot entry.** Install this kernel *alongside* your existing one and leave the old entry intact. If something goes wrong you flip one line in `extlinux.conf` and you're back — no reflashing, no disassembly.

This project was developed exactly that way: a working BSP image as fallback, the mainline kernel as a second entry, iterating over SSH. See [`runtime/extlinux.conf.example`](runtime/extlinux.conf.example).

**Recovery:** power off, put the boot media in another machine, change `default` back to your known-good label.

---

## Quick start (prebuilt binaries)

Prebuilt `Image`, DTB and modules are attached to the [latest Release](../../releases/latest). They are a **convenience build, offered as-is and unsupported** — built from the exact sources in this repo, for the exact hardware listed above.

```bash
# On the device, as root. ADD a boot entry — do not replace your existing one.
tar xf uconsole-cm5-7.1-modules.tar.gz -C /
cp Image-7.1 /boot/
mkdir -p /boot/dtb-7.1 && cp rk3588s-radxa-cm5-uconsole.dtb /boot/dtb-7.1/
```

Then add the boot entry and runtime files — see [Deploy](#4-deploy) and [Runtime configuration](#runtime-configuration) below.

---

## Build from source

Works both **natively on the uConsole** and **cross-compiled from an x86_64 host**; the build script detects which.

### 1. Get the kernel

```bash
git clone --depth=1 -b v7.1 \
  https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git linux-7.1
```

### 2. Apply this repo's additions

```bash
git clone https://github.com/tdeval/uconsole-radxa-cm5-mainline.git
cd linux-7.1

# Panel driver
cp ../uconsole-radxa-cm5-mainline/kernel/panel-cwu50.c drivers/gpu/drm/panel/

# Register it (append — position in the file does not matter)
cat >> drivers/gpu/drm/panel/Kconfig << 'EOF'

config DRM_PANEL_CLOCKWORKPI_CWU50
	tristate "ClockworkPi uConsole CWU50 panel (JD9365DA-H3)"
	depends on OF
	depends on DRM_MIPI_DSI
	depends on BACKLIGHT_CLASS_DEVICE
	depends on REGULATOR
	help
	  ClockworkPi uConsole 5" 720x1280 DSI panel.
	  Supports TXW500170B0 and TXW500170B0-BL (Dec 2025+).
EOF
echo 'obj-$(CONFIG_DRM_PANEL_CLOCKWORKPI_CWU50) += panel-cwu50.o' \
  >> drivers/gpu/drm/panel/Makefile

# Device tree
cp ../uconsole-radxa-cm5-mainline/kernel/rk3588s-radxa-cm5-uconsole.dts \
   arch/arm64/boot/dts/rockchip/
sed -i '/rk3588s-radxa-cm5-io.dtb/a dtb-$(CONFIG_ARCH_ROCKCHIP) += rk3588s-radxa-cm5-uconsole.dtb' \
  arch/arm64/boot/dts/rockchip/Makefile
```

> **Do not** use `sed -i '/^config DRM_PANEL_/i ...'` to insert the Kconfig entry — it matches ~80 lines and inserts a copy before every one of them.

### 3. Configure and build

```bash
cp ../uconsole-radxa-cm5-mainline/kernel/build-uconsole-kernel.sh ~/
KDIR=$PWD ~/build-uconsole-kernel.sh
```

The script regenerates `.config` from `defconfig` + the fragment, verifies the critical symbols are set, builds `Image modules dtbs`, and stages modules. It is safe to re-run after `make distclean` — **the config is never the source of truth, the fragment is.**

Cross-compiling needs `aarch64-linux-gnu-gcc`; native builds need nothing extra. Native build on the CM5 takes roughly an hour with `-j8`.

### 4. Deploy

**Three artifacts must be deployed together. A stale DTB fails silently** — the kernel boots with your old device tree and you chase ghosts. (Ask me how I know.)

```bash
KREL=$(cat include/config/kernel.release)

sudo cp arch/arm64/boot/Image /boot/Image-7.1
sudo mkdir -p /boot/dtb-7.1
sudo cp arch/arm64/boot/dts/rockchip/rk3588s-radxa-cm5-uconsole.dtb /boot/dtb-7.1/
sudo rsync -a --no-o --no-g ~/staging/modules-7.1/lib/modules/$KREL /lib/modules/
```

Add a boot entry to `/boot/extlinux/extlinux.conf` — keep your existing entry:

```
default uconsole-71-mainline

label uconsole-71-mainline
    menu label uConsole mainline 7.1
    kernel /boot/Image-7.1
    fdt /boot/dtb-7.1/rk3588s-radxa-cm5-uconsole.dtb
    append root=PARTUUID=YOUR-PARTUUID-HERE rootfstype=ext4 rootwait rw console=ttyS4,1500000 console=tty1 consoleblank=0 loglevel=7 panic=10
```

> **Use `root=PARTUUID=`, not `root=UUID=`.** This kernel is built without an initramfs, and a bare kernel cannot resolve filesystem UUIDs. Get yours with `lsblk -o NAME,PARTUUID`.
>
> **Do not add `earlycon=`.** It touches UART4 before its clock is ungated and hard-hangs the boot with no output at all.

After rebooting, verify you're actually running what you built:

```bash
uname -r                                                          # 7.1.0
tr -d '\0' < /sys/firmware/devicetree/base/pcie@fe190000/status    # okay
sudo dmesg | grep cwu50                                            # panel: TXW500170B0-BL (new)
```

---

## Runtime configuration

Copy from [`runtime/`](runtime/):

```bash
# REQUIRED — works around the DSI first-enable bug (otherwise: grey screen)
sudo cp runtime/display-kick.service /etc/systemd/system/
sudo systemctl enable display-kick.service

# Full power-off (cuts the AXP rails, not just the CM5 module)
sudo cp runtime/axp-off.sh /usr/lib/systemd/system-shutdown/
sudo chmod +x /usr/lib/systemd/system-shutdown/axp-off.sh

# Bounds the shutdown hang if a driver stalls (hardware watchdog fallback)
sudo mkdir -p /etc/systemd/system.conf.d
sudo cp runtime/reboot-watchdog.conf /etc/systemd/system.conf.d/
```

### Wayland

**sway** reads the panel orientation from the device tree and rotates itself correctly — nothing to configure.

**labwc** does not; give it an autostart:

```bash
mkdir -p ~/.config/labwc
cp runtime/labwc-autostart ~/.config/labwc/autostart
chmod +x ~/.config/labwc/autostart
```

Idle screen-off works with `swayidle` calling `swaymsg output DSI-1 power off` — the backlight really does cut.

Confirm you have hardware acceleration and not a software fallback:

```bash
glxinfo | grep -i renderer     # want "Mali-G610 MC4 (Panfrost)", not "llvmpipe"
```

---

## What's in the device tree

Beyond the stock `rk3588s-radxa-cm5.dtsi`:

- **CWU50 panel** on DSI1 → mipidcphy1 → VOP2 **VP3**, with `rotation = <90>`
- **AXP228 PMU** on bit-banged I²C (CM4 `ID_SD`/`ID_SC` → GPIO1_D7/D6), providing the panel's `vci` (1.8 V) and `iovcc` (3.3 V) rails, plus battery/AC power supplies
- **GPIO backlight** on GPIO1_B1
- **UART4 (`m2` pinmux)** as the debug console — the SoC's default uart2 routes to Mini-PCIe on this chassis and is physically unreachable
- **USB PHYs** (`usbdp_phy0`, `combphy0_ps`, `combphy2_psu`) — without these the dwc3 controllers defer forever and the internal keyboard never appears
- **PCIe** `pcie2x1l2` + 3.3 V regulator for the NVMe board
- **`mmu600_pcie` disabled** — its shutdown handler hangs reboot; PCIe works fine without it

Full pin mapping in [`docs/gpio-map.md`](docs/gpio-map.md).

---

## Serial console

UART4, **1,500,000 baud** (not 115200) on the GPIO connector:

| uConsole pin | Signal | Adapter |
|---|---|---|
| PIN_23 | UART4 TX | RX |
| PIN_19 | UART4 RX | TX |
| PIN_25 | GND | GND |

PL2303x and CH340 adapters **cannot** do 1.5 Mbps. Use a CP2102N, FT232H, or CH343P.

---

## Troubleshooting

The nine things that cost the most time during bring-up — inverted panel detection, the DSI first-enable wedge, the SMMU shutdown hang, the earlycon trap, and more — are written up in [`docs/troubleshooting.md`](docs/troubleshooting.md).

---

## Contributing

Useful things to report:

- **Original (pre-2025) panel:** does auto-detection pick it correctly? `dmesg | grep cwu50`
- **Other adapters / no NVMe board:** what needed changing in the DTS
- **HDMI hotplug**, **backlight dimming**, **charge LED** — all open

## Credits

- [@ak-rex](https://github.com/ak-rex) — the original `panel-cwu50` driver and both JD9365DA-H3 init sequences, without which none of this exists. This driver is a port of that work to the mainline panel API.
- [@dev-null2019](https://github.com/dev-null2019) — Radxa CM5 uConsole device tree overlays that mapped out the hardware
- randomlinuxuser — Arch Linux Radxa CM5 image, used as the fallback system throughout development
- Rockchip / Radxa / Collabora upstream work that put RK3588 DSI2 and DCPHY into mainline

## License

GPL-2.0+, matching the kernel. `panel-cwu50.c` is derived from GPL-2.0+ code by ClockworkPi / ak-rex.
