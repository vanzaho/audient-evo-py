#!/bin/bash
# EVO8 Audio Setup - set EVO8 nodes as default devices
#
# Run manually after connecting EVO8, or via systemd (evo8-setup.service).
# Defaults persist in WirePlumber state across reboots.
#
# Install: ~/.local/bin/evo8-setup.sh

set -euo pipefail

# Main output is the explicit stereo sink from evo8-stereo.conf.
SINK="evo8_main_output"
SOURCE="evo8_mic_1_2"

# Wait for PipeWire graph to settle
sleep 2

# Find node ID from wpctl status output
get_node_id() {
    wpctl status 2>/dev/null | grep -m1 "$1" | grep -oP '\d+(?=\.)' | head -1
}

SINK_ID=$(get_node_id "$SINK")
SOURCE_ID=$(get_node_id "$SOURCE")

if [[ -z "${SINK_ID:-}" ]]; then
    echo "EVO8 not detected (ALSA node '$SINK' not found)"
    echo "Is the device connected? Check: wpctl status"
    exit 1
fi

echo "EVO8 detected, setting defaults..."

wpctl set-default "$SINK_ID"
echo "Default sink: EVO8 Main Output (id=$SINK_ID)"

if [[ -n "${SOURCE_ID:-}" ]]; then
    wpctl set-default "$SOURCE_ID"
    echo "Default source: EVO8 Microphone 1+2 (id=$SOURCE_ID)"
else
    echo "Warning: could not find source '$SOURCE'"
fi

echo ""
echo "EVO8 nodes:"
for node in "$SINK" evo8_output_3_4 evo8_loopback_output evo8_mic_1_2 evo8_mic_3_4 evo8_loopback_capture; do
    nid=$(get_node_id "$node")
    if [[ -n "${nid:-}" ]]; then
        echo "  $node (id=$nid)"
    else
        echo "  $node (not found)"
    fi
done
