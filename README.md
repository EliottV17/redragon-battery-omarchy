# Redragon M916 Pro Battery Widget for Omarchy

A native, standalone battery telemetry widget for the **Redragon M916 Pro 1K** wireless gaming mouse, designed for the **Omarchy** Linux desktop environment (Quickshell).

Provides live battery percentage, real-time ADC voltage telemetry, charge state detection, and a theme-integrated floating card popup through Omarchy's native plugin architecture.

---

## Verified Hardware

Tested and verified on:
* **Operating System:** Omarchy 4.0.4 (Arch Linux with Hyprland & Quickshell)
* **Mouse:** Redragon M916 Pro 1K (Compx CX52850P microcontroller)
* **2.4 GHz Wireless Receiver:** USB VID `3554`, PID `f55d`
* **Direct USB Cable Connection:** USB VID `3554`, PID `f55e`

> **Compatibility Notice:** This widget has been verified exclusively with the Redragon M916 Pro 1K (`3554:f55d` and `3554:f55e`). While other Compx-based mice share similar firmware traits, compatibility is not guaranteed without hardware verification.

---

## Features

* **Dual-Mode Auto-Detection & Priority:**
  * Detects both direct USB cable connection (`3554:f55e`) and 2.4 GHz wireless receiver (`3554:f55d`).
  * Automatically prioritizes direct USB when plugged in and charging, falling back to 2.4 GHz wireless mode when unplugged.
* **Real Hardware Telemetry:**
  * Reads real battery percentage and live ADC voltage (e.g. `3.95 V` / `3946 mV`).
  * Strict packet validation: rejects corrupt checksums, out-of-range percentages, and truncated packets.
  * Real charging detection (`CHARGING` vs `DISCHARGING`).
  * No mock numbers or fake fallbacks: displays `--%` whenever hardware telemetry cannot be confirmed.
* **Native Omarchy Floating Card:**
  * Minimalist, dark-themed popup styled with native Omarchy theme tokens (`Color.popups.background`, `Color.popups.text`, `Color.popups.border`).
  * Large mouse glyph (`󰍽`), connection status, bold percentage, and an animated horizontal progress bar.
  * Two-column telemetry overview:
    * **Left:** Voltage (`V`) and Connection Mode (`USB` / `2.4 GHz`).
    * **Right:** Last update relative time (`Just now`, `1m ago`, `5m ago`) and Device Name.
  * Dismisses on outside click or by pressing <kbd>Esc</kbd>.
  * Includes a discrete manual refresh button (`Refresh` / <kbd>r</kbd> key) alongside automatic 60-second polling.
* **Minimalist Status Bar Indicator:**
  * Shows a clean mouse icon (`󰍽`) and current percentage (`65%` or `󰍽 󱐋 65%` when charging).
  * Uses active Omarchy theme colors at rest, hover, and press.
  * Urgent alert color (red) is displayed **strictly** when battery level is critical (≤ 5% and discharging).
  * Automatically hides when the mouse/dongle is completely disconnected.
* **Asynchronous Architecture with Bounded Timeouts:**
  * Powered by Quickshell's asynchronous `Process` engine with bounded per-node timeouts (~0.4s).
  * Limits candidate queries to the vendor control interface (Interface 1), avoiding interface stalls.

---

## Requirements

* **OS:** Arch Linux with [Omarchy](https://omarchy.org/) 4.0.4
* **Shell:** Quickshell (`omarchy-shell`)
* **Runtime:** Python 3 (standard library only; no pip dependencies required)
* **Permissions:** systemd with udev (for non-root USB access)

---

## Installation

### Step 1: Add Plugin via Omarchy's Native Plugin Manager

Run the official Omarchy command to clone, validate, and enable the plugin:

```bash
omarchy plugin add https://github.com/<your-username>/redragon-battery-omarchy.git --enable
```

Omarchy will clone the repository into `~/.config/omarchy/plugins/local.redragon-battery`, validate its `manifest.json`, register it in the shell catalog, and place it on your status bar.

---

### Step 2: Configure Non-Root USB Permissions (One-Time Setup)

Because Omarchy's `omarchy plugin add` operates purely within unprivileged user space, it intentionally does not execute privileged system scripts. To grant your desktop user read/write access to the mouse without running anything as root:

1. **Install the udev rule:**
   ```bash
   sudo cp ~/.config/omarchy/plugins/local.redragon-battery/udev/69-redragon-battery.rules /etc/udev/rules.d/
   sudo udevadm control --reload-rules && sudo udevadm trigger
   ```

2. **Re-plug Device:**
   Unplug and reconnect the USB dongle and/or USB cable once so systemd applies the new `uaccess` permissions to `/dev/hidraw*`.

#### Why priority 69 (`69-redragon-battery.rules`)?
In systemd-udev, `70-uaccess.rules` tags devices and `73-seat-late.rules` runs the `uaccess` builtin that grants filesystem ACLs to the logged-in graphical user. Placing the rule at priority `69` ensures the `TAG+="uaccess"` is attached before `70-uaccess.rules` and `73-seat-late.rules` execute.

#### Resolving Previous / Legacy Rules
If you previously installed manual rules such as `70-redragon-battery.rules` or `99-redragon-battery.rules`, inspect them to confirm they belong to this device, then remove them to prevent duplicate rule evaluation:
```bash
sudo rm -f /etc/udev/rules.d/70-redragon-battery.rules /etc/udev/rules.d/99-redragon-battery.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

---

## Usage

* **Toggle Floating Card:** Click the mouse battery icon in your Omarchy status bar.
* **Dismiss Floating Card:** Click anywhere outside the card or press <kbd>Esc</kbd>.
* **Manual Refresh:** Click `Refresh` inside the card or press <kbd>r</kbd> while the card is focused.
* **Terminal Test:** You can run the reader directly in your terminal at any time:
  ```bash
  ~/.config/omarchy/plugins/local.redragon-battery/redragon_battery.py --pretty
  ```

---

## Updating

Update to the latest version at any time using Omarchy's native plugin manager:

```bash
omarchy plugin update local.redragon-battery
```

Omarchy will fast-forward the git checkout, re-validate the manifest, and refresh the running shell.

---

## Uninstallation

1. **Remove the plugin via Omarchy:**
   ```bash
   omarchy plugin remove local.redragon-battery
   ```
   This automatically unloads the plugin, removes the widget from your status bar layout, and backs up the folder.

2. **(Optional) Remove the udev rule:**
   ```bash
   sudo rm -f /etc/udev/rules.d/69-redragon-battery.rules
   sudo udevadm control --reload-rules && sudo udevadm trigger
   ```

---

## Troubleshooting

### 1. Widget displays `--%` or "Timeout waiting for RF telemetry"
* **Mouse in Sleep Mode:** In 2.4 GHz wireless mode, the mouse powers down its radio when idle to conserve battery. Move or click the mouse to wake it up, then press `Refresh`.
* **Wired Mode Radio Deactivation:** When the USB cable is plugged in, the mouse deliberately disables its 2.4 GHz transmitter. Ensure the udev rule is loaded so the reader can query the direct USB endpoint (`3554:f55e`).

### 2. "Permission denied on /dev/hidrawX"
* Verify that `/etc/udev/rules.d/69-redragon-battery.rules` exists.
* Reconnect the USB receiver or cable.
* Check permissions: `ls -l /dev/hidraw*` should show `+` in the permissions string (e.g. `crw-rw----+`), confirming that systemd applied an ACL for your user. You can also inspect permissions with `getfacl /dev/hidrawX`.

---

## Known Limitations

* **Discrete Battery Reporting:** The Compx CX52850P microcontroller firmware reports battery percentage in discrete steps (e.g. increments of 5% or 10%). Step changes between readings reflect actual firmware reporting.
* **No Remaining Autonomy Estimation:** The manufacturer protocol does not provide estimated discharge rates or battery capacity; remaining time is deliberately omitted rather than estimated with inaccurate guesswork.
* **Radio Deactivation in Wired Mode:** When connected via USB cable, the mouse shuts off its 2.4 GHz link. The reader handles this by prioritizing direct USB communication over `3554:f55e`.

---

## Security & Hardware Safety

* **Read-Only Telemetry:** The Python reader strictly transmits standard Report ID `0x08`, Opcode `0x04` (`BatteryLevel`) queries with official Compx CRC checksums.
* **No Flash Memory Writes:** The widget never writes to microcontroller Flash memory registers, never alters DPI stages, polling rates, sensor calibration, button mappings, or RF pairing states.
* **Secure Access Control:** Uses systemd user access control (`TAG+="uaccess"`) restricted to the logged-in seat user, avoiding insecure world-writable permissions (`MODE="0666"`).
* **Unprivileged User Execution:** Quickshell, the QML interface, and the Python reader execute entirely under standard desktop user privileges.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
