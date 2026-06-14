#!/usr/bin/env bash
# uninstall.sh - Remove Audient EVO 8 PipeWire/WirePlumber config
#
# Usage: bash uninstall.sh

set -euo pipefail

PW_CONF="$HOME/.config/pipewire/pipewire.conf.d"
WP_CONF="$HOME/.config/wireplumber/wireplumber.conf.d"
SYSTEMD_USER="$HOME/.config/systemd/user"
LOCAL_BIN="$HOME/.local/bin"

info() { echo -e "\033[1;34m==>\033[0m $*"; }
ok()   { echo -e "\033[1;32m  ->\033[0m $*"; }

removed=0

for f in \
  "$PW_CONF/evo8-stereo.conf" \
  "$WP_CONF/51-evo8.conf" \
  "$WP_CONF/alsa-soft-mixer.conf" \
  "$LOCAL_BIN/evo8-setup.sh"; do
  if [[ -f "$f" ]]; then
    rm "$f"
    ok "Removed $f"
    removed=$((removed + 1))
  fi
done

if [[ -f "$SYSTEMD_USER/evo8-setup.service" ]]; then
    systemctl --user disable evo8-setup.service 2>/dev/null || true
    rm "$SYSTEMD_USER/evo8-setup.service"
    ok "Disabled and removed $SYSTEMD_USER/evo8-setup.service"
    removed=$((removed + 1))
fi

if [[ $removed -eq 0 ]]; then
    info "No EVO 8 WirePlumber config found - nothing to remove."
    exit 0
fi

systemctl --user daemon-reload 2>/dev/null || true
info "Restarting PipeWire and WirePlumber"
systemctl --user restart pipewire.service pipewire-pulse.service wireplumber.service 2>/dev/null || true

echo ""
info "Done! Removed $removed file(s)."
echo "  Run 'wpctl status' to verify audio routing."
