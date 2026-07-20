#!/usr/bin/env bash
# One-time setup: turns the Raspi's wlan0 into a standalone AP for the control link.
# Run with sudo on the Raspi itself. Idempotent-ish; review before running on a
# Pi that's also used for anything else (this claims wlan0 fully).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

apt-get update
apt-get install -y hostapd dnsmasq

systemctl unmask hostapd
systemctl stop hostapd dnsmasq

# Static IP for wlan0 (AP side)
cat >> /etc/dhcpcd.conf <<'EOF'

interface wlan0
    static ip_address=192.168.4.1/24
    nohook wpa_supplicant
EOF

cp "$SCRIPT_DIR/hostapd.conf" /etc/hostapd/hostapd.conf
cp "$SCRIPT_DIR/dnsmasq.conf" /etc/dnsmasq.d/drone-control.conf

sed -i 's|^#DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd
if ! grep -q '^DAEMON_CONF=' /etc/default/hostapd; then
    echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' >> /etc/default/hostapd
fi

echo "IMPORTANT: edit hostapd.conf's wpa_passphrase before enabling on a real flight box."
echo "Then: systemctl enable --now dhcpcd hostapd dnsmasq (or reboot)."
