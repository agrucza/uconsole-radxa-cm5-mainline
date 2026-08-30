# Troubleshooting

Everything below was hit for real while bringing mainline 7.1 up on a uConsole + Radxa CM5. Most of these fail *silently* — no error, no log, just something that doesn't work — which is what makes them expensive. Where a cause is inferred rather than proven, it says so.

> **Distro note:** this was done with **Arch Linux ARM** on the device and Arch on the build host. The kernel-level content is distro-agnostic, but package names, `mkinitcpio` vs `dracut`, and bootloader conventions differ elsewhere. Debian/Ubuntu users in particular: your boot entries are likely managed differently, and several packages have other names (`dwarves` vs Arch's `pahole`, for instance).

---

## Symptom quick reference

| What you see | Jump to |
|---|---|
| Boot is completely silent, status LED static, nothing on any screen | [earlycon hangs the boot](#earlycon-hangs-the-boot-before-anything-prints) |
| Kernel seems not to boot, but LED heartbeats | [It probably booted — you can't reach it](#it-probably-booted--you-just-cant-reach-it) |
| Kernel panics on root mount | [`root=UUID=` needs an initramfs](#rootuuid-doesnt-work-without-an-initramfs) |
| LCD backlight on, screen uniform **grey** | [DSI first-enable wedge](#lcd-is-uniform-grey-dsi-first-enable-wedge) |
| LCD completely dark, not even glowing | [Backlight latch](#lcd-completely-dark-backlight-latched-off) |
| LCD shows garbled stripes | [Wrong panel init sequence](#lcd-shows-stripes-or-garbage) |
| Console text rotated, `fbcon=rotate:` ignored | [fbcon rotation needs a config symbol](#console-rotation-does-nothing) |
| Internal keyboard/trackball absent | [USB PHYs not enabled](#no-internal-keyboard-or-trackball) |
| `lspci` prints nothing at all | [PCIe controller never registered](#lspci-prints-nothing) |
| `reboot`/`poweroff` hangs, needs battery pull | [SMMU shutdown hang](#reboot-or-poweroff-hangs) |
| Device tree change had no effect | [Stale DTB](#your-device-tree-change-did-nothing) |
| HDMI black | [Connect before power-on](#hdmi-stays-black) |
| Build fails: "recursive dependency detected" | [Kconfig `select` vs `depends on`](#build-recursive-dependency-detected) |
| Build fails: "unterminated argument list" | [Truncated file](#build-unterminated-argument-list-invoking-macro) |
| Build fails: "recipe commences before first target" | [Broken DTS Makefile edit](#build-recipe-commences-before-first-target) |

---

## Debugging without a serial cable

The uConsole's default debug UART is physically unreachable (see [below](#the-default-debug-uart-is-unreachable)), and wiring up UART4 takes bench time you may not have. These three techniques carried the entire bring-up documented here without a serial adapter ever being connected.

### Read the failed boot's log from your fallback kernel

If the system got far enough for systemd to start, **the journal captured everything** — including the full kernel dmesg — and it survives the reboot. Boot your known-good kernel and read the previous boot:

```bash
journalctl --list-boots          # find the failed attempt
journalctl -b -1 -k --no-pager > /tmp/failed-boot.txt
grep -iE "cwu50|panel|dsi|vop|drm" /tmp/failed-boot.txt
```

This is how "the kernel doesn't boot" turned out to be "the kernel booted perfectly and got a different DHCP lease."

If `--list-boots` shows *no* entry for the attempt, userspace never started — the failure is earlier (root mount or before).

**Post-mortem from another machine.** If the uConsole won't boot at all, pull the boot media, mount it elsewhere, and read the journal off it directly — no working device required:

```bash
sudo mount /dev/sdX2 /mnt
sudo journalctl --root=/mnt --list-boots
sudo journalctl --root=/mnt -b -1 -k --no-pager > failed-boot.txt
```

This is the single most useful recovery trick here: the logs from a machine that no longer boots are still sitting on its filesystem.

### netconsole: stream kernel messages over ethernet

Invaluable for shutdown/reboot hangs, where the screen is already off and nothing gets written to disk.

```bash
# Build the module against your kernel
make -j$(nproc) drivers/net/netconsole.ko

# On the device:
sudo insmod netconsole.ko \
  netconsole=6666@DEVICE_IP/end0,6666@HOST_IP/HOST_MAC

# On the host:
nc -ul 6666 | tee trace.log

# Verify the pipe works before relying on it:
echo NETCONSOLE-TEST | sudo tee /dev/kmsg
```

> **If host and device are on different subnets**, netconsole cannot route — it is raw ethernet. Use your **gateway's** MAC (`ip neigh show <gateway-ip>`), not the host's.

### `initcall_debug`: name the device that hangs shutdown

With this on, the kernel prints each device's name immediately *before* calling its shutdown callback. Combine with netconsole and the last name in the stream is your culprit.

```bash
echo Y | sudo tee /sys/module/kernel/parameters/initcall_debug
echo Y | sudo tee /sys/module/printk/parameters/ignore_loglevel
sudo systemctl reboot
```

Both are runtime-writable — no cmdline edit, no extra reboot.

### Ground truth files worth knowing

```bash
sudo mount -t debugfs none /sys/kernel/debug     # not persistent across reboots

/sys/kernel/debug/devices_deferred               # drivers stuck waiting on a supplier
/sys/kernel/debug/gpio                           # every GPIO: owner, direction, level
/sys/kernel/debug/clk/clk_summary                # is that clock actually running?
/sys/kernel/debug/regulator/regulator_summary    # is that rail actually on, and who uses it
/sys/kernel/debug/dri/*/state                    # full DRM atomic state
/sys/firmware/devicetree/base/...                # the DT the kernel is ACTUALLY running
```

That last one settles "did my DTS change take effect" in one command, and would have saved a full debugging session here.

---

## Boot failures

### earlycon hangs the boot before anything prints

**Symptom:** Absolutely nothing. No console output anywhere, status LED static (no heartbeat), no network, no panic-reboot.

**Cause:** `earlycon=uart8250,mmio32,0xfeb70000` makes the kernel write to UART4's registers within the first milliseconds — before any clock driver runs. U-Boot only initialised *its own* console UART, so UART4's peripheral clock is still gated. On RK3588 an MMIO access to a clock-gated peripheral doesn't fault cleanly; it stalls the interconnect and wedges the CPU. *(Inferred from the failure signature, not instrumented.)*

**Fix:** Drop `earlycon` entirely. `console=ttyS4,1500000` is fine — the real serial driver manages clocks properly, much later in boot.

The vendor BSP entries get away with `earlycon` only because they point at the one UART that U-Boot already brought up.

### `root=UUID=` doesn't work without an initramfs

**Symptom:** Kernel boots, then panics unable to mount root — or with `rootwait`, hangs forever with a live heartbeat and no userspace.

**Cause:** A bare kernel understands `/dev/...`, `PARTUUID=` and `PARTLABEL=`. Resolving a *filesystem* UUID requires userspace tooling that lives in an initramfs. Vendor boot entries can use `root=UUID=` because they ship one.

**Fix:** `lsblk -o NAME,PARTUUID`, then `root=PARTUUID=...`.

### It probably booted — you just can't reach it

**Symptom:** "The new kernel doesn't boot." No SSH.

**Cause:** Mainline may present a different NIC name (`end0` vs `eth0`) and a different MAC than the vendor kernel, so your DHCP server hands out **a different IP**. The machine is up and sshd is listening; you're knocking on the old address.

**Fix:** Check the DHCP lease table on your router, or scan the subnet. Confirm afterwards with `journalctl -b -1 | grep -iE "dhcp|sshd"` — the previous boot's log will show both the lease and `Server listening on 0.0.0.0 port 22`.

**Tell-tale:** a heartbeating status LED and a blinking ethernet link LED mean the kernel is alive. A truly dead kernel doesn't blink anything.

---

## Display

Three failure appearances mean three different things. Getting this vocabulary right saves hours:

| Appearance | Meaning |
|---|---|
| **Uniform grey** (backlight visibly on) | Panel powered and DISPON, but receiving **no high-speed video**. Init commands failed. |
| **Completely dark**, no glow even under a flashlight | Backlight off. Says nothing about the video path. |
| **Stripes / garbage** | Video arriving, but wrong init sequence or wrong timing. |
| **Synced but black** on an external monitor | Can be a *zombie*: U-Boot configured scanout and the kernel's DRM never took over. |

### LCD is uniform grey (DSI first-enable wedge)

**Symptom:** Backlight on, screen uniformly grey. Writing to `/dev/fb0` changes nothing. No DRM errors, no `flip_done` timeouts — the atomic state looks perfect.

**Diagnosis:**
```bash
sudo dmesg | grep -iE "dsi2|command interface"
```
```
dw-mipi-dsi2 fde30000.dsi: command interface is busy
dw-mipi-dsi2 fde30000.dsi: failed to write command header
...repeating, once per init command, 20 ms timeout each
```

**Cause:** On the first pre-enable after cold probe, the DSI2 command interface comes up wedged. Every DCS write of the panel init sequence times out, so the panel is never initialised. The `post_disable` path performs a full controller/PHY reset, so a *second* enable works perfectly.

**Confirm it in ten seconds:**
```bash
sudo sh -c 'echo 1 > /sys/class/graphics/fb0/blank; sleep 2; echo 0 > /sys/class/graphics/fb0/blank'
```
If the console appears, this is your bug.

**Workaround:** `runtime/display-kick.service` performs that cycle once at boot.

**Status:** This looks like a genuine mainline `dw-mipi-dsi2` first-enable bug rather than anything board-specific. Reproducer and traces are available; reporting upstream is on the list.

### LCD completely dark (backlight latched off)

**Symptom:** No glow at all, even shining a flashlight at an angle. Meanwhile `/sys/class/backlight/*/brightness` reads non-zero and `/sys/kernel/debug/gpio` shows the enable pin `out hi`.

**Cause (inferred):** The OCP8178 is a one-wire pulse-protocol chip that latches its state as long as its supply rail stays up — and **warm reboots never drop that rail**. A crashed boot can leave the enable line low long enough to latch the chip *off*, and a steady-high `gpio-backlight` cannot unlatch it, because steady levels aren't the protocol it speaks.

**Fix:** Full power removal (battery disconnect) resets the latch. From a genuine cold start with the enable line coming up high, it powers on correctly. A proper OCP8178 driver port would make this robust — and give brightness steps.

**Diagnostic worth doing first:** shine a bright flashlight at the dark LCD at an angle. If you can make out a ghost of the console, the panel is working and it's purely a backlight problem.

### LCD shows stripes or garbage

**Cause:** Wrong init sequence for your panel revision. The Dec-2025 **TXW500170B0-BL** needs a different sequence from the original TXW500170B0 (different gamma power: ±4.9 V vs ±4.5 V, different GIP mapping, different TCON timing).

**Check which one was detected:**
```bash
sudo dmesg | grep cwu50
```
```
panel-cwu50 fde30000.dsi.0: GPIO probe: new panel (final check at prepare)
panel-cwu50 fde30000.dsi.0: panel: TXW500170B0-BL (new)
```

If it reports the wrong revision, see the next two entries.

### Panel revision detection is inverted from what you'd guess

The reset GPIO is declared `GPIO_ACTIVE_LOW` in the device tree. The BL panel pulls RESX **physically low** on the FPC — but `gpiod_get_value()` returns the **logical** level, so physical-low reads as **1**.

```c
ctx->is_new_panel = gpiod_get_value_cansleep(ctx->id_gpio);   /* correct */
ctx->is_new_panel = !gpiod_get_value_cansleep(ctx->id_gpio);  /* WRONG */
```

Reasoning in physical terms and adding the negation costs you a build cycle and a grey screen.

### The RDID confirmation check does not port from the RPi driver

The original driver confirms the panel by reading DCS register `0x04` and matching `0x39`. On the Rockchip DSI2 read path you get `93 00 00` instead — the JD9365 signature byte, different framing.

Treat RDID as **set-only** confirmation (`if (buf[0] == 0x39) is_new = true;`) and rely on the GPIO probe as primary. Don't let a failed RDID match *clear* a correct GPIO detection.

### Console rotation does nothing

**Symptom:** Console text sideways. `fbcon=rotate:N` on the cmdline does nothing, `/sys/class/graphics/fbcon/rotate_all` does nothing, the DT `rotation` property does nothing. Three mechanisms, all dead.

**Cause:** They share one gate: **`CONFIG_FRAMEBUFFER_CONSOLE_ROTATION=y`**, which arm64 `defconfig` leaves off. Without it fbcon's rotation code is compiled out entirely and every interface silently no-ops.

**Fix:** Enable it. Then `rotation = <90>` in the panel node is correct for this chassis — 270 renders upside-down.

Once the DRM orientation property is doing the work, `rotate_all` being inert again is *expected*: the helper owns rotation and fbcon's own rotator is out of the loop.

### HDMI stays black (console only)

**Scope:** this affects the **boot console**, not Wayland. Under sway the external monitor works at its native resolution and hotplug is picked up mid-session.

**Cause:** fbcon only lights HDMI if the sink is present when the pipeline first commits at boot; it never re-probes afterwards.

**Fix:** connect the monitor before power-on — or just start your compositor, which handles it properly.

**Note:** every mid-session HDMI test in console mode is therefore misleading. A long detour here chasing a suspected 10-bpc deep-colour problem was entirely a red herring caused by testing via hotplug at the console.

**Also expected in console mode:** both outputs mirror a single fbcon framebuffer and rotation is a global console property, so one output is necessarily crooked. Wayland fixes this with per-output transforms and native resolutions:

```
DSI-1      720x1280   transform=90
HDMI-A-1   1280x1024  transform=normal
```

---

## Missing hardware

### No internal keyboard or trackball

**Diagnosis:**
```bash
sudo cat /sys/kernel/debug/devices_deferred
```
```
fc000000.usb    dwc3: failed to initialize core
fcd00000.usb    dwc3: failed to initialize core
```

**Cause:** The dwc3 controllers need their PHYs, and if those nodes aren't enabled they defer probe forever. The uConsole's internal hub (keyboard, trackball, consumer keys — one composite `1EAF:0024` device) hangs off `usb_host0`.

**Fix:** enable `&usbdp_phy0`, `&combphy0_ps`, `&combphy2_psu`, and set `dr_mode = "host"` on `usb_host0_xhci` (without Type-C role-switch hardware, OTG can idle in an undefined role).

**Verify:**
```bash
ls /sys/bus/usb/devices/          # expect entries beyond the root hubs
cat /proc/bus/input/devices       # expect "ClockworkPI uConsole Keyboard"
```

### `lspci` prints nothing

Not "no device found" — **zero lines means the host bridge itself never registered.** A working controller shows at least its root port with nothing plugged in.

Two independent causes, both seen here:

1. **The PCIe node is disabled in the device tree.** Check what the kernel is *actually* running:
   ```bash
   for n in /sys/firmware/devicetree/base/pcie@*; do
     echo "$n -> $(tr -d '\0' < $n/status)"
   done
   ```
   `pcie@fe190000` (`pcie2x1l2`) must read `okay`.

2. **The combo PHY is a module.** `CONFIG_PHY_ROCKCHIP_NANENG_COMBO_PHY=m` with a built-in host driver and no initramfs: the host probes early, finds no PHY provider, defers, and on an all-`=y` system nothing ever rescues it. Set it **`=y`**.

**Working output looks like:**
```
rockchip-dw-pcie a41000000.pcie: PCIe Gen.2 x1 link up
pci 0004:40:00.0: [1d87:3588] type 01 class 0x060400 PCIe Root Port
pci 0004:41:00.0: [144d:a808] type 00 class 0x010802 PCIe Endpoint
nvme nvme0: pci function 0004:41:00.0
```

**Note:** PCIe works fine with `mmu600_pcie` disabled (see below) — the device just falls back to direct DMA.

---

## Shutdown and power

### Reboot or poweroff hangs

**Symptom:** `systemctl reboot` hangs. Backlight goes off, ethernet LEDs stay lit and active, power LED stays on. Long-pressing power does nothing; only battery removal recovers.

**Key distinction:** `echo b > /proc/sysrq-trigger` reboots *perfectly*. That bypasses `device_shutdown()` entirely — so the hang is a driver shutdown callback, not PSCI.

**Diagnosis:** netconsole + `initcall_debug` (see above). The trace ended at:
```
arm-smmu-v3 fc900000.iommu: shutdown        ← last line, then silence
```

**Cause:** the PCIe SMMU's shutdown handler hangs — RK3588 MMU600 wired-IRQ erratum territory (the boot log also flags `msi_domain absent - falling back to wired irqs`).

**Fix:**
```dts
&mmu600_pcie {
	status = "disabled";
};
```

**Safety net regardless:** systemd already arms the hardware watchdog during shutdown, but the default timeout is 10 minutes — nobody waits that long, so the board looks permanently dead when it would have rescued itself. Shrink it:
```ini
# /etc/systemd/system.conf.d/reboot-watchdog.conf
[Manager]
RebootWatchdogSec=30s
```

### Poweroff leaves the machine half-on

**Symptom:** OS shuts down, CM5 module LED goes off, but the case power LED stays lit and ethernet stays powered. A short press won't restart it.

**Cause:** `system-power-controller` lives on the RK806 (the CM5 module's PMIC), so poweroff cuts the *module* only. The mainboard's AXP228 keeps its rails up.

**Fix:** a systemd shutdown hook that tells the AXP to cut everything (register `0x32`, bit 7 = shutdown):
```sh
#!/bin/sh
[ "$1" = "poweroff" ] && i2cset -f -y 9 0x34 0x32 0xc3
```
in `/usr/lib/systemd/system-shutdown/`, executable. It runs at the very end, after unmounts, with the kernel still alive.

**Confirm your bus number first** — `9` is this build's enumeration and depends on probe order:
```bash
i2cdetect -l
```
```
i2c-0   unknown   rk3x-i2c              N/A
i2c-9   unknown   i2c-axp               N/A     ← the bit-banged AXP bus
i2c-10  unknown   DesignWare HDMI QP    N/A
```
The AXP is the adapter named after the `i2c-gpio` node (`i2c-axp` here), at address `0x34`.

---

## Build failures

### Build: "recursive dependency detected"

```
drivers/regulator/Kconfig:2: symbol REGULATOR is selected by DRM_PANEL_CLOCKWORKPI_CWU50
```

**Cause:** `select REGULATOR` in the panel's Kconfig entry creates a dependency cycle through `CHARGER_MANAGER` → `EXTCON` → `USB_MTU3` → `MFD_SYSCON`.

**Fix:** `depends on REGULATOR` instead. It's already enabled in `defconfig`; there's nothing to force.

### Build: "unterminated argument list invoking macro"

```
panel-cwu50.c:281:57: error: unterminated argument list invoking macro 'dcs_write_seq'
```

**Cause:** the file is **truncated** — copy-paste or an editor buffer cut it off mid-line. Not an API problem.

**Check:**
```bash
wc -l drivers/gpu/drm/panel/panel-cwu50.c   # expect 612
tail -3 drivers/gpu/drm/panel/panel-cwu50.c # expect MODULE_LICENSE("GPL");
```

### Build: "recipe commences before first target"

**Cause:** a botched `sed` insertion into `arch/arm64/boot/dts/rockchip/Makefile`. That file uses **one `dtb-$(CONFIG_ARCH_ROCKCHIP) += foo.dtb` line per DTB**, not backslash continuations — inserting a continuation line breaks Make syntax.

**Fix:** `git checkout -- arch/arm64/boot/dts/rockchip/Makefile`, then append a plain line in the same style as its neighbours.

### 81 copies of your Kconfig entry

`sed -i '/^config DRM_PANEL_/i ...'` inserts before **every** matching line, and there are ~80 of them.

```bash
git checkout -- drivers/gpu/drm/panel/Kconfig
cat >> drivers/gpu/drm/panel/Kconfig << 'EOF'
...
EOF
grep -c DRM_PANEL_CLOCKWORKPI_CWU50 drivers/gpu/drm/panel/Kconfig   # must be 1
```

Position in Kconfig is irrelevant to the build. Append.

### Your device tree change did nothing

**Symptom:** you edited the DTS, rebuilt, rebooted — and behaviour is identical. No error anywhere.

**Cause:** you deployed the kernel but not the DTB (or vice versa). This project has **three** deployment artifacts — `Image`, the DTB, and modules — and a stale one fails *silently*: the old device tree just keeps working, slightly wrong.

**Always verify against the live tree, not your source file:**
```bash
tr -d '\0' < /sys/firmware/devicetree/base/pcie@fe190000/status
sudo xxd /sys/firmware/devicetree/base/dsi@fde30000/panel@0/rotation   # 5a = 90
```

### Lost `.config` after `make distclean`

Not a problem, by design: `.config` is never the source of truth here. `build-uconsole-kernel.sh` regenerates it from `defconfig` + the tracked fragment. Your source additions (driver, DTS, Kconfig/Makefile edits) are working-tree changes and survive `distclean` untouched — confirm with:

```bash
git status --short | grep -E "cwu50|uconsole|Kconfig|Makefile"
```

---

## Miscellaneous

### The default debug UART is unreachable

`uart2` (the RK3588S default) routes to Mini-PCIe on this chassis — not to the GPIO connector. Use **uart4 with the `m2` pinmux**: RX on GPIO1_B2 (PIN_19), TX on GPIO1_B3 (PIN_23), `stdout-path = "serial4:1500000n8"`.

### 1,500,000 baud, not 115200

The RK3588S default console rate. **PL2303x and CH340 adapters cannot do it.** Use CP2102N, FT232H, or CH343P.

### sway won't install: wlroots 404

Arch Linux ARM occasionally has sway ahead of its exact `wlrootsX.YY` ABI sub-package. `pacman -Sy` and retry; if it persists, either use **labwc** (same wlroots stack, proves the same things) or build wlroots from source at the version sway expects. The `wlroots-git` AUR package refuses aarch64 due to a stale arch list in its PKGBUILD, not a real incompatibility.

### Confirm you actually have GPU acceleration

Compositors fall back to software rendering silently and still look fine at idle.

```bash
glxinfo | grep -i renderer     # want "Mali-G610 MC4 (Panfrost)", not "llvmpipe"
glmark2                        # ~2600 here; llvmpipe scores in the low double digits
```

`vulkaninfo` returning nothing is expected — panvk is still experimental, and Wayland compositors use GLES anyway.

### Battery isn't charging (it probably is)

```bash
grep -H . /sys/class/power_supply/*/{status,online,current_now,capacity}
```
`axp22x-ac/online: 1`, `axp20x-battery/status: Charging`, and a **positive** `current_now` mean it's charging fine. The orange charge LED being dark is a separate, purely cosmetic issue: the AXP's CHGLED pin is under manual control (register `0x32` reads `0x43`) rather than being driven by the charger state machine.
