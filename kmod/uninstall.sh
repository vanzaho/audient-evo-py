#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ ! -f "$SCRIPT_DIR/dkms.conf" ]]; then
  echo "Error: dkms.conf not found next to this script."
  exit 1
fi

# Single source of truth for the module name/version: dkms.conf.
eval "$(grep -E '^PACKAGE_(NAME|VERSION)=' "$SCRIPT_DIR/dkms.conf")"
MODULE_NAME="$PACKAGE_NAME"
MODULE_VERSION="$PACKAGE_VERSION"

if [[ $EUID -ne 0 ]]; then
  echo "This script must be run as root (use sudo)."
  exit 1
fi

# Purge the current module plus any legacy names from older installs.
ALL_MODULES=("$MODULE_NAME" evo4_raw)

# Unload if currently loaded
for mod in "${ALL_MODULES[@]}"; do
  if lsmod | grep -q "^${mod} "; then
    echo "Unloading module ${mod}..."
    rmmod "$mod" 2>/dev/null || true
  fi
done

# Remove every DKMS version (installed, built, or just added), not only the
# current one, so old versions don't hang around after a version bump.
if command -v dkms &>/dev/null; then
  for mod in "${ALL_MODULES[@]}"; do
    [[ -d "/var/lib/dkms/${mod}" ]] || continue
    for verdir in "/var/lib/dkms/${mod}"/*/; do
      ver=$(basename "$verdir")
      [[ "$ver" == "*" ]] && continue
      echo "Removing DKMS module ${mod}/${ver}..."
      dkms remove "${mod}/${ver}" --all 2>/dev/null || true
    done
  done
fi

# Remove all source trees and any manually-installed (non-DKMS) modules
for mod in "${ALL_MODULES[@]}"; do
  for src in /usr/src/${mod}-*; do
    if [[ -d "$src" ]]; then
      echo "Removing source ${src}..."
      rm -rf "$src"
    fi
  done
  rm -f "/etc/modules-load.d/${mod}.conf"
  find /lib/modules -path '*/extra/*' -name "${mod}.ko*" -delete 2>/dev/null || true
done
depmod -a 2>/dev/null || true

# Remove udev rules (current and any legacy)
echo "Removing udev rules..."
rm -f /etc/udev/rules.d/99-evo*.rules
udevadm control --reload-rules 2>/dev/null || true

# Remove systemd user services if installed
if [[ -n "${SUDO_USER:-}" ]]; then
  TARGET_USER="$SUDO_USER"
  TARGET_HOME=$(eval echo ~"$TARGET_USER")
  SYSTEMD_USER_DIR="$TARGET_HOME/.config/systemd/user"

  # Disable template instances and remove the template unit
  for inst in evo4 evo8; do
    sudo -u "$TARGET_USER" systemctl --user disable "evo-load-config@${inst}.service" 2>/dev/null || true
  done
  rm -f "$SYSTEMD_USER_DIR/evo-load-config@.service"

  # Remove legacy per-device service files from older installs
  for SYSTEMD_SERVICE in "$SYSTEMD_USER_DIR"/evo*-load-config.service; do
    if [[ -f "$SYSTEMD_SERVICE" ]]; then
      service=$(basename "$SYSTEMD_SERVICE")
      echo "Removing legacy systemd service ${service} for user '$TARGET_USER'..."
      sudo -u "$TARGET_USER" systemctl --user disable "$service" 2>/dev/null || true
      rm "$SYSTEMD_SERVICE"
    fi
  done
fi

echo "Done. ${MODULE_NAME} has been fully removed."
