# Cross-Compiling an Arch Linux Kernel for the ClockworkPi uConsole (Radxa CM5)
### With TXW500170B0-BL LCD Display Support

> **Host requirement:** An x86_64 machine running Arch Linux.  
> **Target:** uConsole with Radxa CM5 module, booting Arch Linux ARM from microSD.

---

## Overview

The Radxa CM5 (RK3588S SoC) requires a downstream kernel tree maintained by the community — specifically **ak-rex/ClockworkRadxa-linux** — paired with device-tree overlays from **dev-null2019/radxa-cm5-uconsole** to expose uConsole-specific hardware (display, keyboard, power management). The new TXW500170B0-BL panel is handled through the `cwu50_panel` DT overlay, which initialises the MIPI-DSI panel connected via the uConsole mainboard.

**Key repositories:**
- Kernel: https://github.com/ak-rex/ClockworkRadxa-linux (branch `linux-6.1-stan-rkr4.1`)
- Overlays: https://github.com/dev-null2019/radxa-cm5-uconsole
- Reference Arch build: https://github.com/0xrushi/ClockworkRadxa-linux (branch `arch-linux-6.1-stan-rkr4.1`)

---

## Step 1 — Install Host Build Dependencies

```bash
sudo pacman -Syu
sudo pacman -S --needed \
  base-devel git bc flex bison openssl ncurses \
  dtc uboot-tools pahole swig python python-setuptools \
  aarch64-linux-gnu-gcc aarch64-linux-gnu-binutils \
  parted e2fsprogs dosfstools rsync wget
```

---

## Step 2 — Set Cross-Compilation Environment Variables

```bash
export ARCH=arm64
export CROSS_COMPILE=aarch64-linux-gnu-
```

Add these to your `~/.bashrc` or prefix every `make` call with them.

---

## Step 3 — Clone the Kernel Source

```bash
mkdir -p ~/uconsole/build
cd ~/uconsole

git clone --depth=1 \
  -b linux-6.1-stan-rkr4.1 \
  https://github.com/ak-rex/ClockworkRadxa-linux.git

cd ClockworkRadxa-linux
```

> **Note:** The `linux-6.1-stan-rkr4.1` branch is the current community-tested branch for the Radxa CM5 in the uConsole. It includes the RK3588S platform support, the uConsole power management patches, and the `cwu50` MIPI panel driver that drives both the older TXW500170B0 and the newer TXW500170B0-BL display.

---

## Step 4 — Configure the Kernel

Apply the Rockchip base defconfig, which is the correct starting point for the RK3588S SoC:

```bash
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- rockchip_linux_defconfig
```

### Optional: Open menuconfig to review/add options

```bash
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- menuconfig
```

Key config options to verify are enabled:

| Option | Purpose |
|---|---|
| `CONFIG_DRM_PANEL_CLOCKWORKPI_CWU50` | uConsole MIPI panel driver (covers both panel revisions) |
| `CONFIG_DRM_ROCKCHIP` | Rockchip DRM display subsystem |
| `CONFIG_DRM_MIPI_DSI` | MIPI-DSI bus support |
| `CONFIG_PWM_ROCKCHIP` | Backlight PWM |
| `CONFIG_MFD_AXP20X_I2C` | AXP power management IC |
| `CONFIG_BATTERY_AXP20X` | Battery/charging support |
| `CONFIG_INPUT_CLOCKWORKPI_JOYSTICK` | Thumbstick axis input |
| `CONFIG_KEYBOARD_GPIO` | GPIO keyboard matrix |
| `CONFIG_SPI_ROCKCHIP` | SPI controller |
| `CONFIG_MMC_SDHCI_OF_DWMSHC` | eMMC/SD card host |

> **For the TXW500170B0-BL panel specifically:** The new panel differs from the original only in its DSI initialisation sequence. This is handled entirely within the `cwu50_panel.dts` device-tree overlay (not in the kernel config), so no special kernel option is needed beyond the above.

---

## Step 5 — Build the Kernel, Modules, and DTBs

```bash
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j$(nproc) Image modules dtbs
```

This will produce:
- `arch/arm64/boot/Image` — the kernel image
- `arch/arm64/boot/dts/rockchip/rk3588s-radxa-cm5*.dtb` — device tree blobs
- `*.ko` module files throughout the tree

### Install modules to a staging directory

```bash
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
  INSTALL_MOD_PATH=~/uconsole/modules-staging \
  modules_install
```

---

## Step 6 — Clone and Build the Device-Tree Overlays

The uConsole-specific hardware (display initialisation, AXP power management, display routing) is described in overlays, not baked into the base DTB.

```bash
cd ~/uconsole
git clone https://github.com/dev-null2019/radxa-cm5-uconsole.git
cd radxa-cm5-uconsole/devicetree_overlays
mkdir -p build
```

The `.dts` files use C preprocessor includes, so they must be run through `cpp` before passing to `dtc`:

```bash
KDIR=~/uconsole/ClockworkRadxa-linux
ODIR=~/uconsole/radxa-cm5-uconsole/devicetree_overlays

for f in axp20x.dts cwu50_panel.dts displaystuff.dts; do
  base="${f%.dts}"
  cpp -P -nostdinc \
    -I "$KDIR/include" \
    -I "$KDIR/scripts/dtc/include-prefixes" \
    -I "$KDIR/arch/arm64/boot/dts" \
    -I "$KDIR/arch/arm64/boot/dts/rockchip" \
    -I "$ODIR" \
    -I "$ODIR/dt-bindings" \
    -undef -D__DTS__ -x assembler-with-cpp \
    "$ODIR/$f" > "$ODIR/build/${base}.pp.dts"

  dtc -@ -I dts -O dtb \
    -o "$ODIR/build/${base}.dtbo" \
    "$ODIR/build/${base}.pp.dts"
done

ls -lh ~/uconsole/radxa-cm5-uconsole/devicetree_overlays/build/
```

You should see three `.dtbo` files:
- `axp20x.dtbo` — AXP20x PMIC / battery management
- `cwu50_panel.dtbo` — MIPI-DSI panel (TXW500170B0 / TXW500170B0-BL)
- `displaystuff.dtbo` — display routing, backlight, rotation

---

## Step 7 — Prepare the microSD Card

> Replace `/dev/sdX` with your actual SD card device. **Double-check** with `lsblk` before proceeding — this is destructive.

```bash
export SD=/dev/sdX

sudo wipefs -a "$SD"
sudo sgdisk --zap-all "$SD"

# Leave 16 MiB gap at the start for U-Boot
sudo parted -s "$SD" \
  mklabel gpt \
  mkpart boot ext4 16MiB 528MiB \
  mkpart root ext4 528MiB 100%

sudo mkfs.ext4 -L BOOT "${SD}1"
sudo mkfs.ext4 -L ROOT "${SD}2"
```

### Mount partitions

```bash
sudo mount "${SD}2" /mnt
sudo mkdir -p /mnt/boot
sudo mount "${SD}1" /mnt/boot
```

---

## Step 8 — Flash U-Boot to the SD Card

The Radxa CM5 will not boot from SD without U-Boot written to the raw beginning of the card. Use Radxa's prebuilt SPL+U-Boot binary:

```bash
cd ~/uconsole

# Download the Radxa CM5 U-Boot SPI image
wget https://github.com/radxa-build/radxa-cm5-rpi-cm4-io/releases/latest/download/radxa-cm5-rpi-cm4-io_bookworm_cli_b3.output.img.xz

# Extract only the U-Boot sectors (first 16 MiB) and write them
xzcat radxa-cm5-rpi-cm4-io_bookworm_cli_b3.output.img.xz \
  | sudo dd of="$SD" bs=512 count=32768 conv=notrunc status=progress
```

> Alternatively, build U-Boot from source using Radxa's BSP: `https://github.com/radxa/u-boot`  
> The SPL (Second Program Loader) for RK3588S must be written starting at sector 64 (offset 0x8000).

---

## Step 9 — Install the Arch Linux ARM Rootfs

```bash
cd /tmp
wget http://os.archlinuxarm.org/os/ArchLinuxARM-aarch64-latest.tar.gz

sudo bsdtar -xpf ArchLinuxARM-aarch64-latest.tar.gz -C /mnt
```

### Write fstab using UUIDs

```bash
ROOT_UUID=$(sudo blkid -s UUID -o value "${SD}2")
BOOT_UUID=$(sudo blkid -s UUID -o value "${SD}1")

sudo tee /mnt/etc/fstab <<EOF
UUID=${ROOT_UUID}  /      ext4  rw,noatime  0 1
UUID=${BOOT_UUID}  /boot  ext4  rw,noatime  0 2
EOF
```

---

## Step 10 — Install Kernel, DTBs, Modules, and Overlays

```bash
KDIR=~/uconsole/ClockworkRadxa-linux

# Kernel image
sudo cp "$KDIR/arch/arm64/boot/Image" /mnt/boot/Image

# Rockchip DTBs
sudo mkdir -p /mnt/boot/dtbs/rockchip
sudo rsync -a "$KDIR/arch/arm64/boot/dts/rockchip/" /mnt/boot/dtbs/rockchip/

# Kernel modules
sudo rsync -a ~/uconsole/modules-staging/lib/modules/ /mnt/lib/modules/

# DT overlays
sudo mkdir -p /mnt/boot/overlays
sudo cp ~/uconsole/radxa-cm5-uconsole/devicetree_overlays/build/*.dtbo \
  /mnt/boot/overlays/
```

---

## Step 11 — Create the Bootloader Configuration

U-Boot will read `extlinux/extlinux.conf` from the boot partition:

```bash
sudo mkdir -p /mnt/boot/extlinux
sudo tee /mnt/boot/extlinux/extlinux.conf <<'EOF'
timeout 5
default ArchLinuxARM

label ArchLinuxARM
  kernel /Image
  fdt /dtbs/rockchip/rk3588s-radxa-cm5-rpi-cm4-io.dtb
  fdtoverlays /overlays/axp20x.dtbo /overlays/cwu50_panel.dtbo /overlays/displaystuff.dtbo
  append root=/dev/mmcblk0p2 rw rootwait console=ttyS2,1500000n8 console=tty1
EOF
```

> **Base DTB note:** `rk3588s-radxa-cm5-rpi-cm4-io.dtb` is the correct base for the Radxa CM5 in the uConsole, as the uConsole mainboard uses the Raspberry Pi CM4 IO pin-compatible socket. The three overlays then layer uConsole-specific hardware on top of it.

---

## Step 12 — Pre-apply Overlays into a Combined DTB (Optional but recommended)

Some U-Boot builds do not support `fdtoverlays`. As a fallback, merge them at build time:

```bash
DTB=/mnt/boot/dtbs/rockchip/rk3588s-radxa-cm5-rpi-cm4-io.dtb
OVERLAYS_DIR=/mnt/boot/overlays
OUT=/mnt/boot/dtbs/rockchip/rk3588s-radxa-uconsole-combined.dtb

sudo fdtoverlay \
  -i "$DTB" \
  -o "$OUT" \
  "$OVERLAYS_DIR/axp20x.dtbo" \
  "$OVERLAYS_DIR/cwu50_panel.dtbo" \
  "$OVERLAYS_DIR/displaystuff.dtbo"
```

Then update `extlinux.conf` to use `fdt /dtbs/rockchip/rk3588s-radxa-uconsole-combined.dtb` and remove the `fdtoverlays` line.

---

## Step 13 — Sync and Unmount

```bash
sync
sudo umount /mnt/boot
sudo umount /mnt
```

---

## Step 14 — First Boot

Insert the microSD into the uConsole and power on. Expected behaviour:

- The RK3588S ROM loads the U-Boot SPL from the raw sectors before partition 1.
- U-Boot finds `extlinux.conf` on the first ext4 partition and loads the kernel + DTBs.
- The `cwu50_panel` overlay initialises the MIPI-DSI interface and the TXW500170B0-BL panel.
- The kernel boots to Arch Linux ARM. Default login: `alarm` / `alarm`, root: `root` / `root`.

### If the display stays black on first cold boot

This is a known timing-sensitivity issue with the uConsole MIPI panel drivers. Try:

1. Reboot rather than cold boot — the panel often initialises correctly on a warm reboot.
2. Check `dmesg | grep -i panel` or `dmesg | grep -i dsi` via UART (115200 baud on the debug header) or via SSH over ethernet.
3. Ensure the `cwu50_panel.dtbo` and `displaystuff.dtbo` are being applied (visible in `dmesg` as overlay application messages).

---

## Step 15 — Post-Boot System Setup (chroot or on-device)

### Install kernel headers (for DKMS / out-of-tree modules)

After booting, install the matching kernel headers. If building them yourself:

```bash
# On the host, produce a headers package into a staging dir
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
  INSTALL_HDR_PATH=~/uconsole/headers-staging \
  headers_install

sudo rsync -a ~/uconsole/headers-staging/ \
  /mnt/usr/src/linux-$(cat ~/uconsole/ClockworkRadxa-linux/include/config/kernel.release)/
```

### Enable NetworkManager (if using the Arch ARM rootfs)

```bash
# In a chroot or on-device:
systemctl enable NetworkManager
systemctl enable systemd-resolved
```

### Known hardware limitations on Radxa CM5

| Feature | Status |
|---|---|
| Display (TXW500170B0-BL) | ✅ Working via `cwu50_panel` overlay |
| Keyboard / trackball | ✅ Working |
| USB host | ✅ Working |
| SD card | ✅ Working |
| Battery / charging (AXP) | ✅ Working via `axp20x` overlay |
| 4G expansion module | ✅ Working |
| Audio (speakers) | ⚠️ Partial — no analog DAC on Radxa CM5 |
| Internal Wi-Fi / BT | ❌ Not available (no Wi-Fi module on Radxa CM5) |
| HDMI out | ⚠️ Requires hardware modification |

---

## References

- Forum thread (build walkthrough): https://forum.clockworkpi.com/t/building-uconsole-cm5-radxa-image-for-arch-linux/20150
- Forum thread (Arch Linux image): https://forum.clockworkpi.com/t/arch-linux-for-radxa-cm5-on-uconsole/21569
- Rex's Bookworm 6.1.y for Radxa: https://forum.clockworkpi.com/t/bookworm-6-1-y-for-the-radxa-cm5-uconsole/16315
- New screen images (RPi CM5 reference, kernel 6.12.67): https://forum.clockworkpi.com/t/updated-images-for-new-uconsole-screens/21666
- dev-null2019 overlays: https://github.com/dev-null2019/radxa-cm5-uconsole
- ClockworkPi official uConsole repo: https://github.com/clockworkpi/uConsole
