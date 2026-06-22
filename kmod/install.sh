#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ ! -f "$SCRIPT_DIR/dkms.conf" ]]; then
    echo "Error: dkms.conf not found next to this script."
    exit 1
fi

# Single source of truth for the module name/version: dkms.conf.
# Extract just these two assignments so the rest of dkms.conf (arrays, MAKE,
# ${kernelver}) isn't evaluated under this script's `set -u`.
eval "$(grep -E '^PACKAGE_(NAME|VERSION)=' "$SCRIPT_DIR/dkms.conf")"
MODULE_NAME="$PACKAGE_NAME"
MODULE_VERSION="$PACKAGE_VERSION"
SRC_DIR="/usr/src/${MODULE_NAME}-${MODULE_VERSION}"

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root (use sudo)."
    exit 1
fi

# Check required dependencies
if ! command -v make &>/dev/null; then
    echo "Error: 'make' is not installed."
    echo "Install it with your package manager (e.g. apt install build-essential, pacman -S base-devel)"
    exit 1
fi

# Check kernel headers
KDIR="/lib/modules/$(uname -r)/build"
if [[ ! -d "$KDIR" ]]; then
    echo "Error: kernel headers not found at $KDIR"
    echo "Install them (e.g. apt install linux-headers-\$(uname -r), pacman -S linux-headers)"
    exit 1
fi

# Check for DKMS (optional but recommended)
USE_DKMS=0
if command -v dkms &>/dev/null; then
    USE_DKMS=1
else
    echo "Warning: 'dkms' is not installed."
    echo "  Kernel modules are version-stamped: after a kernel update the module"
    echo "  will stop loading and you will need to re-run this install script."
    echo "  DKMS automates that rebuild. It is recommended:"
    echo "    apt install dkms  OR  pacman -S dkms"
    echo ""
    read -p "Continue without DKMS? (y/n) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# One udev rule + systemd template cover both models; no device choice needed.
DEVICES=(evo4 evo8)

if [[ ! -f "$SCRIPT_DIR/99-evo.rules" ]]; then
    echo "Error: 99-evo.rules not found in $SCRIPT_DIR"
    exit 1
fi

# Clean up any legacy evo4_raw install before (re)installing
if lsmod | grep -q "^evo4_raw"; then
    echo "Unloading legacy evo4_raw module..."
    rmmod evo4_raw
fi
if [[ $USE_DKMS -eq 1 ]] && dkms status "evo4_raw/${MODULE_VERSION}" 2>/dev/null | grep -q "evo4_raw"; then
    echo "Removing legacy evo4_raw DKMS module..."
    dkms remove "evo4_raw/${MODULE_VERSION}" --all
fi

if [[ $USE_DKMS -eq 1 ]]; then
    if dkms status "${MODULE_NAME}/${MODULE_VERSION}" 2>/dev/null | grep -q "${MODULE_NAME}"; then
        echo "Removing existing DKMS module..."
        dkms remove "${MODULE_NAME}/${MODULE_VERSION}" --all
    fi

    echo "Copying module source to ${SRC_DIR}..."
    rm -rf "$SRC_DIR"
    mkdir -p "$SRC_DIR"
    cp "$SCRIPT_DIR"/{evo_raw.c,Makefile,dkms.conf} "$SRC_DIR/"

    echo "Adding, building and installing via DKMS..."
    dkms add "${MODULE_NAME}/${MODULE_VERSION}"
    dkms build "${MODULE_NAME}/${MODULE_VERSION}"
    dkms install "${MODULE_NAME}/${MODULE_VERSION}"
else
    echo "Building module..."
    make -C "$SCRIPT_DIR" all

    echo "Installing module..."
    make -C "$SCRIPT_DIR" install

    echo "$MODULE_NAME" > /etc/modules-load.d/evo_raw.conf  # auto-load on boot
fi

# Install udev rule (covers both EVO4 and EVO8)
echo "Installing udev rule..."
cp "$SCRIPT_DIR/99-evo.rules" /etc/udev/rules.d/
udevadm control --reload-rules

echo "Loading module..."
modprobe "$MODULE_NAME"

# Add user to dialout group
if [[ -n "${SUDO_USER:-}" ]]; then
    if groups "$SUDO_USER" | grep -qw 'dialout'; then
        echo "User '$SUDO_USER' is already in the 'dialout' group."
    else
        echo ""
        echo "Users must be in the 'dialout' group to access /dev/evo4 or /dev/evo8 without sudo."
        read -p "Add '$SUDO_USER' to the 'dialout' group now? (y/n) " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            usermod -a -G dialout "$SUDO_USER"
            echo "Done. Log out and back in (or reboot) for the group change to take effect."
        else
            echo "Skipped. Run manually when ready: sudo usermod -a -G dialout $SUDO_USER"
        fi
    fi
fi

# Optional: Setup auto-load config on device connection
echo ""
read -p "Enable auto-load of saved config when device is connected? (y/n) " -n 1 -r SETUP_AUTOLOAD
echo ""

if [[ $SETUP_AUTOLOAD =~ ^[Yy]$ ]]; then
    if [[ -n "${SUDO_USER:-}" ]]; then
        TARGET_USER="$SUDO_USER"
    else
        echo "Error: Could not determine user (not run via sudo?)."
        echo "Skipping auto-load setup."
    fi

    if [[ -n "${TARGET_USER:-}" ]]; then
        TARGET_HOME=$(eval echo ~"$TARGET_USER")
        EVOCTL_PATH="$TARGET_HOME/.local/bin/evoctl"

        if [[ -f $EVOCTL_PATH ]]; then
            SYSTEMD_USER_DIR="$TARGET_HOME/.config/systemd/user"
            TARGET_UID=$(id -u "$TARGET_USER")

            echo "Installing auto-load service template (user: $TARGET_USER)"
            install -D -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
                "$SCRIPT_DIR/evo-load-config@.service" \
                "$SYSTEMD_USER_DIR/evo-load-config@.service"

            sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" systemctl --user daemon-reload
            for dev in "${DEVICES[@]}"; do
                sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" systemctl --user enable "evo-load-config@${dev}.service"
            done

            echo "Auto-load config enabled."
            echo ""
            echo "To test, reconnect your device or log out and back in."
            for dev in "${DEVICES[@]}"; do
                echo "View logs with: journalctl --user -u evo-load-config@${dev}.service -f"
            done
        else
            echo "Error: 'evoctl' not found at $EVOCTL_PATH"
            echo "Install it first with: pipx install ."
            echo "Skipping auto-load setup."
        fi
    fi
fi

echo ""
echo "Done. ${MODULE_NAME} is installed and loaded."
for dev in "${DEVICES[@]}"; do
    echo "  /dev/${dev} will be available when the device is connected."
done
if [[ $USE_DKMS -eq 1 ]]; then
    echo "  The module will auto-rebuild on kernel updates (DKMS)."
else
    echo "  Note: Without DKMS, re-run this install script after each kernel update."
fi
