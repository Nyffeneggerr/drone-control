#!/usr/bin/env bash
# Sync raspi/ and web/ to the drone's Raspberry Pi over ssh, as siblings —
# server.py resolves web/ relative to raspi/ (WEB_DIR = raspi/../web), so
# both must land in that same relative layout on the Pi.
set -euo pipefail

PI_HOST="${PI_HOST:-pi@192.168.2.152}"
PI_DEST_RASPI="${PI_DEST_RASPI:-~/raspi}"
PI_DEST_WEB="${PI_DEST_WEB:-~/web}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

rsync -avz --delete \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.venv/' \
  "$SCRIPT_DIR/" "$PI_HOST:$PI_DEST_RASPI/"

rsync -avz --delete \
  "$REPO_ROOT/web/" "$PI_HOST:$PI_DEST_WEB/"
