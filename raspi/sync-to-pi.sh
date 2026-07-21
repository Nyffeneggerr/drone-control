#!/usr/bin/env bash
# Sync this raspi/ folder to the drone's Raspberry Pi over ssh.
set -euo pipefail

PI_HOST="${PI_HOST:-pi@192.168.2.152}"
PI_DEST="${PI_DEST:-~/raspi}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

rsync -avz --delete \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.venv/' \
  "$SCRIPT_DIR/" "$PI_HOST:$PI_DEST/"
