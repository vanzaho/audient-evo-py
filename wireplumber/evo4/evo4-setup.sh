#!/bin/bash
# EVO4 Audio Setup — set EVO4 nodes as default devices
#
# Run manually after connecting EVO4, or via systemd (evo4-setup.service).
# Defaults persist in WirePlumber state across reboots.
#
# Install: ~/.local/bin/evo4-setup.sh

set -euo pipefail

# Main output is the explicit stereo sink from evo4-stereo.conf.
SINK="evo4_main_output"
SOURCE="evo4_mic"

# Wait for PipeWire graph to settle
sleep 2

# Find node ID from wpctl status output
get_node_id() {
    wpctl status 2>/dev/null | grep -m1 "$1" | grep -oP '\d+(?=\.)' | head -1
}

SINK_ID=$(get_node_id "$SINK")
SOURCE_ID=$(get_node_id "$SOURCE")

if [[ -z "${SINK_ID:-}" ]]; then
    echo "EVO4 not detected (ALSA node '$SINK' not found)"
    echo "Is the device connected? Check: wpctl status"
    exit 1
fi

echo "EVO4 detected, setting defaults..."

wpctl set-default "$SINK_ID"
echo "Default sink: EVO4 Main Output (id=$SINK_ID)"

if [[ -n "${SOURCE_ID:-}" ]]; then
    wpctl set-default "$SOURCE_ID"
    echo "Default source: EVO4 Microphone (id=$SOURCE_ID)"
else
    echo "Warning: could not find source '$SOURCE'"
fi

echo ""
echo "EVO4 nodes:"
for node in "$SINK" evo4_loopback_output evo4_mic evo4_loopback_capture; do
    nid=$(get_node_id "$node")
    if [[ -n "${nid:-}" ]]; then
        echo "  $node (id=$nid)"
    else
        echo "  $node (not found)"
    fi
done
