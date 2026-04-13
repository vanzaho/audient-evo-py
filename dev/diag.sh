#!/usr/bin/env bash
set -euo pipefail

dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python3 "$dir/diag.py"
