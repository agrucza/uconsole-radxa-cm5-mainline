# Debian 13 on the eMMC with this kernel

The upstream project was brought up on Arch Linux ARM from microSD. This is the Debian path: Radxa's Debian image on the CM5's eMMC, upgraded in place to Debian 13 (Trixie), with the mainline kernel from this repo as a second boot entry. Everything here was done on a Radxa CM5 (32 GB / 256 GB eMMC) in an original-panel uConsole with the HackerGadgets adapter and [AIO v2](aio-v2.md).

## Why Trixie

Debian 12 (Bookworm) boots this kernel fine, but the GPU stays on `llvmpipe`: panthor needs Mesa 25. Trixie brings Mesa 25, `libgpiod` 2 (needed by the `aio` tool and by a working `meshtasticd`) and sway 1.10. Upgrade first, then spend time on the desktop.

## Order that worked

Have a bootable fallback in place before every risky step.

1. **Flash the eMMC** with Radxa's `radxa-cm5-rpi-cm4-io_bookworm_cli_b3` image. Put the CM5 into Maskrom (button on the module, or the switch on the HackerGadgets adapter, whose "Flash" USB-C port lets you flash the module inside the uConsole). Plug into a **USB-A** port on the host; on USB-C, `rkdeveloptool db` hangs at "Downloading bootloader".

   ```bash
   sudo rkdeveloptool ld                                  # must say Maskrom
   sudo rkdeveloptool db rk3588_spl_loader_v1.15.113.bin
   sudo rkdeveloptool wl 0 radxa-cm5-rpi-cm4-io_bookworm_cli_b3.img
   sudo rkdeveloptool rd
   ```

2. **Make a rescue microSD** from the same image (`dd ... oflag=direct conv=fsync`, with a good card reader; a cheap one dropped the connection mid-write). Radxa's U-Boot boots the SD before the eMMC, so from the SD you can mount the eMMC root (`mmcblk1p3`) and repair `extlinux.conf`.

3. **Deploy mainline** (an upstream release or your own build) next to the Radxa kernel, as in the [README](../README.md#4-deploy). Two Debian-specific traps:
   - Copy modules with `rsync` or `cp`. **Never `tar -C /`** a modules tarball on Debian: if the archive contains `lib/` as a directory, tar replaces the `/lib → usr/lib` symlink and the system no longer boots. Recovery from the rescue SD: move the modules to `/usr/lib/modules`, recreate the symlink.
   - Use `fdt` (not `fdtdir`) and `root=PARTUUID=` in the boot entry. Switch `default` only after you have tested the rescue SD.

4. **Runtime files** from `runtime/`: `display-kick.service`, `axp-off.sh`, `reboot-watchdog.conf`, exactly as in the README.

5. **First boot in the uConsole only after a true cold start**: battery disconnected, wait a minute. A module that comes warm from the IO board gives a grey display and a dead keyboard, and so does a nearly empty battery; see [battery.md](battery.md).

6. **Upgrade to Trixie.** Switch the sources from `bookworm` to `trixie`, remove `bookworm-backports` and any third-party source (the Meshtastic repo, for example) first. Then `apt update`, `apt upgrade --without-new-pkgs`, `apt full-upgrade`. Answer `N` to the config prompts for `zramswap`, `plymouthd.conf` and `chrony.conf`. Check `extlinux.conf` afterwards (next section).

7. **Build your own kernel** if you need extra modules, for example `rtw88_8812au` for an RTL8812AU WiFi dongle (the fragment in `build-uconsole-kernel.sh` includes it). Build on the Radxa IO board with 12 V, not in the device on battery. On Debian the build dependencies are `build-essential bc bison flex libssl-dev libelf-dev dwarves python3 rsync`. DKMS works against the build tree afterwards if `/lib/modules/<release>/build` points at it.

## Boot entries and the apt hook

Radxa's `u-boot-menu` package regenerates `/boot/extlinux/extlinux.conf` from a trigger (`u-boot-update`) and drops every entry it did not write, which is the mainline entry. Two measures:

- Put the packages on hold so upgrades do not pull in new versions that misbehave: `sudo apt-mark hold u-boot-menu u-boot-radxa-cm5-rpi-cm4-io`. Remove the Radxa kernel meta packages and `radxa-overlays-dkms`; the Radxa kernel itself (6.1.x) stays as the emergency entry (no display, but SSH works).
- Keep a reference copy of the working file and install [`runtime/debian/99-restore-extlinux`](../runtime/debian/99-restore-extlinux), which restores it after any apt run that lost the mainline entry:

  ```bash
  sudo cp /boot/extlinux/extlinux.conf /root/extlinux.conf.mainline
  sudo cp runtime/debian/99-restore-extlinux /etc/apt/apt.conf.d/
  ```

  The hook looks for a label starting with `uconsole-`; rename the check if your labels differ, and refresh the reference copy whenever you change the boot menu on purpose.

A boot menu that has served well: Radxa's `l0`/`l0r` entries (emergency), one entry for the upstream release, one for your own build with the plain DTB, and one for your own build with the [AIO DTB](aio-v2.md#the-aio-device-tree) as the default. [`runtime/extlinux.conf.example`](../runtime/extlinux.conf.example) shows the shape.

`needrestart` does not know the mainline kernel and nags after every apt run; silence its kernel hint:

```bash
echo '$nrconf{kernelhints} = 0;' | sudo tee /etc/needrestart/conf.d/no-kernel-hint.conf
```

## Radxa leftovers

Radxa's image is a Debian with a layer of BSP packages on top, and that layer does not go away with the release upgrade. Some of it quietly overrides Trixie's own files through **dpkg diversions**: the package moves Debian's file aside as `*.bak` and puts its own copy in place, upgrades and even `apt install --reinstall` land in the `.bak`, and `dpkg -V` stays happy because it checks the diverted file. Two of these bit here.

- **`radxa-system-config-rockchip` breaks GDM.** It diverts `/usr/share/gdm/gdm.schemas` to a copy from an older GDM. Trixie's GDM 48 asks that file for `daemon/RemoteLoginEnable`, does not find it, and dies at start with

  ```
  Gdm:ERROR:../common/gdm-settings-direct.c:148:gdm_settings_direct_get_boolean: assertion failed: (entry != NULL)
  ```

  The same package blacklists `panfrost` in `/etc/modprobe.d` for Radxa's vendor GPU stack; harmless on this kernel only because the G610 uses `panthor`. Removing it takes Radxa's `task-rk3588` and `task-rockchip` meta packages along and nothing else; the Radxa kernel package stays.

  ```bash
  sudo apt purge radxa-system-config-rockchip radxa-system-config-rockchip-glamor task-rk3588 task-rockchip
  grep -c RemoteLoginEnable /usr/share/gdm/gdm.schemas     # 1
  ```

- **`radxa-desktop-branding`** puts Radxa's logo on the GDM login screen through the `vendor-logos` alternative and diverts a few KDE and SDDM files. Its removal script trips over its own diversions when both the diverted file and the `.bak` exist; delete the diverted-in copy it names and run the purge again:

  ```bash
  sudo apt purge radxa-desktop-branding        # may fail on /etc/skel/.face, /etc/xdg/kcm-about-distrorc, ...
  sudo rm -f /etc/skel/.face /etc/xdg/kcm-about-distrorc /usr/share/sddm/themes/breeze/theme.conf
  sudo apt purge radxa-desktop-branding
  ```

- **`radxa-sddm-theme`** cannot be removed once the branding package is gone: its removal script does a plain `rm` on a theme file that no longer exists, dpkg stops, and every later apt run ends with "1 not fully installed or removed". Make the script tolerant and let dpkg finish:

  ```bash
  sudo sed -i -e 's|^\(\s*\)rm "|\1rm -f "|' -e 's|^\(\s*dpkg-divert .*\)$|\1 \|\| true|' /var/lib/dpkg/info/radxa-sddm-theme.postrm
  sudo dpkg --remove radxa-sddm-theme
  sudo apt install -f
  ```

To see what else is diverted: `dpkg-divert --list | grep -v "by [^r]"`. What remained here and does no harm: `radxa-firmware` (diverts a few firmware blobs), `rsetup`, the held U-Boot packages, and the Radxa kernel as the emergency boot entry.

One more thing to know about `rsetup`: its package trigger runs `u-boot-update`, so **every apt run that touches it rewrites `extlinux.conf`**. That is what the apt hook above is for; keep the reference copy current after every deliberate change to the boot menu.

## Desktop

Two desktops have run on this system; both need Mesa 25 from Trixie and the panthor kernel driver, and both rotate the panel in software.

**sway**, started from `.bash_profile` on tty1 (no display manager, no autologin). Config points that matter on this device:

```
set $mod Mod1                       # Alt: the uConsole keyboard has no usable Super key
output DSI-1 transform 90
input type:keyboard xkb_layout us
exec swayidle -w timeout 120 'swaymsg "output DSI-1 power off"' resume 'swaymsg "output DSI-1 power on"'
```

`foot` and `wofi` fit the screen.

**GNOME**, `gnome-core` with GDM, since 2026-09-20. Clear the Radxa leftovers above first, or GDM will not start. Delete the sway autostart from `.bash_profile`, since GDM takes tty1, and check that `graphical.target` is the default.

**Disable suspend before the first battery session.** GNOME suspends automatically after 20 minutes idle on battery, and suspend-to-RAM does not work on this board with this kernel: the SoC enters deep sleep and never resumes, the power button does not bring it back, and only removing the battery ends it. Mask it at the systemd level so no desktop setting can trigger it:

```bash
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type 'nothing'
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'
```

**The power button after that.** GNOME's default action for a short press is suspend too, and with the targets masked a short press now does nothing at all (under sway, where logind handles the key, it powers off). Give it a job:

```bash
gsettings set org.gnome.settings-daemon.plugins.power power-button-action 'interactive'   # or 'nothing'
```

A long hold is a different path and needs no setting: the key is wired to the AXP228's PWRON pin, and the PMIC cuts all rails itself after the hold time in its register 0x36 (`sudo i2cget -f -y 9 0x34 0x36`; 0x59 here, bit 3 enabled, 6 seconds). That works with the SoC frozen, because the SoC is not involved, and the AXP keeps its registers, unlike a battery pull. It is a hard cut for the filesystem, so it is the way out of a hang, not a way to shut down.

At 1280×720 on five inches GNOME is usable at 100 %; Large Text under Accessibility is the middle ground. The brightness slider and idle dimming work through `/sys/class/backlight` with this fork's [OCP8178 driver](../README.md#backlight-dimming). If the login screen greets you by the wrong name after a user rename, that is the full-name field in `/etc/passwd`, not the login: `sudo chfn -f "Name" user`.

With either desktop, confirm the GPU is in use with `glxinfo | grep -i renderer` (want Panfrost, not llvmpipe).

## WiFi

An RTL8812AU module (Skyworth board, U.FL to SMA pigtails, two antennas) on the mainboard's internal USB works with mainline `rtw88_8812au` from your own build and the firmware `rtw88/rtw8812a_fw.bin` from `firmware-realtek`. NetworkManager names it `wlx...`. There is no need for an out-of-tree driver.

## Keyboard controller in DFU mode

If the keyboard vanishes after a reboot and `lsusb` shows `1eaf:0003 Maple DFU`, the keyboard MCU dropped into its bootloader (happened once, around the Trixie upgrade, probably coincidence). A cold start brings it back. If it ever sticks, the firmware can be reflashed with `dfu-util`.

## Backups before the risky steps

Before the Trixie upgrade and before any `extlinux.conf` surgery, a tarball of `/boot`, `/lib/modules`, `/etc` and `/root` on a USB stick is cheap insurance. Restoring from the rescue SD is a five-minute job with it and a long evening without.
