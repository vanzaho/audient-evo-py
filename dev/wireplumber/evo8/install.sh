#!/usr/bin/env bash
# install.sh - Install Audient EVO 8 PipeWire/WirePlumber config
#
# What it does:
#   1. Backs up existing configs
#   2. Installs loopback modules, WP rules, soft mixer config
#   3. Installs setup script + systemd service
#   4. Restarts PipeWire + WirePlumber
#   5. Sets EVO 8 stereo nodes as default devices
#
# Usage: bash install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="$HOME/.config/evo-audio-backup/$(date +%Y%m%d-%H%M%S)"

PW_CONF="$HOME/.config/pipewire/pipewire.conf.d"
WP_CONF="$HOME/.config/wireplumber/wireplumber.conf.d"
SYSTEMD_USER="$HOME/.config/systemd/user"
LOCAL_BIN="$HOME/.local/bin"

info() { echo -e "\033[1;34m==>\033[0m $*"; }
warn() { echo -e "\033[1;33m==> WARNING:\033[0m $*"; }
ok()   { echo -e "\033[1;32m  ->\033[0m $*"; }

# Backup existing configs
info "Backing up existing configs to $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"

for f in \
  "$PW_CONF/evo8-stereo.conf" \
  "$WP_CONF/51-evo8.conf" \
  "$WP_CONF/alsa-soft-mixer.conf" \
  "$SYSTEMD_USER/evo8-setup.service" \
  "$LOCAL_BIN/evo8-setup.sh"; do
  if [[ -f "$f" ]]; then
    rel="${f#"$HOME"/}"
    mkdir -p "$BACKUP_DIR/$(dirname "$rel")"
    cp "$f" "$BACKUP_DIR/$rel"
  fi
done
ok "Backup complete"

info "Installing PipeWire loopback config"
mkdir -p "$PW_CONF"
cp "$SCRIPT_DIR/evo8-stereo.conf" "$PW_CONF/evo8-stereo.conf"
ok "evo8-stereo.conf -> $PW_CONF/"

info "Installing WirePlumber device rules"
mkdir -p "$WP_CONF"
cp "$SCRIPT_DIR/51-evo8.conf" "$WP_CONF/51-evo8.conf"
ok "51-evo8.conf -> $WP_CONF/"

info "Installing ALSA soft mixer config"
cp "$SCRIPT_DIR/alsa-soft-mixer.conf" "$WP_CONF/alsa-soft-mixer.conf"
ok "alsa-soft-mixer.conf -> $WP_CONF/"

info "Installing setup script"
mkdir -p "$LOCAL_BIN"
cp "$SCRIPT_DIR/evo8-setup.sh" "$LOCAL_BIN/evo8-setup.sh"
chmod +x "$LOCAL_BIN/evo8-setup.sh"
ok "evo8-setup.sh -> $LOCAL_BIN/"

info "Installing systemd user service"
mkdir -p "$SYSTEMD_USER"
cp "$SCRIPT_DIR/evo8-setup.service" "$SYSTEMD_USER/evo8-setup.service"
systemctl --user daemon-reload
systemctl --user enable evo8-setup.service 2>/dev/null
ok "evo8-setup.service enabled (sets defaults at login)"

info "Restarting PipeWire and WirePlumber"
systemctl --user restart pipewire.service pipewire-pulse.service wireplumber.service

sleep 3

info "Setting EVO 8 as default audio device"

get_node_id() {
    wpctl status 2>/dev/null | grep -m1 "$1" | grep -oP '\d+(?=\.)' | head -1 || true
}

SINK_ID=$(get_node_id "evo8_main_output")
if [[ -n "${SINK_ID:-}" ]]; then
    wpctl set-default "$SINK_ID"
    ok "Default sink: EVO 8 Main Output (id=$SINK_ID)"
else
    warn "Could not find EVO 8 output - is the device connected?"
    warn "Run 'evo8-setup.sh' manually after connecting the device"
fi

SOURCE_ID=$(get_node_id "evo8_mic_1_2")
if [[ -n "${SOURCE_ID:-}" ]]; then
    wpctl set-default "$SOURCE_ID"
    ok "Default source: evo8_mic_1_2 (id=$SOURCE_ID)"
fi

echo ""
info "Configuration summary"
echo ""
echo "  Installed:"
echo "    $PW_CONF/evo8-stereo.conf"
echo "    $WP_CONF/51-evo8.conf"
echo "    $WP_CONF/alsa-soft-mixer.conf"
echo "    $LOCAL_BIN/evo8-setup.sh"
echo "    $SYSTEMD_USER/evo8-setup.service"
echo ""
echo "  Verify:"
echo "    wpctl status"
echo "    pactl info | grep 'Default Sink'"
echo "    pw-top"
echo ""
echo "  Backup at: $BACKUP_DIR"
echo ""
info "Done!"
