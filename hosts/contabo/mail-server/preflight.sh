#!/usr/bin/env bash
# Read-only mail preflight: no service, DNS or firewall changes.
set -euo pipefail

echo "MAIL PREFLIGHT — READ ONLY"
echo "Host: $(hostname)"
echo "Date (UTC): $(date -u +%FT%TZ)"
echo
echo "== Existing public mail DNS =="
for kind in MX A AAAA TXT; do
  case "$kind" in
    MX) name="iniyanjoseph.com" ;;
    A|AAAA) name="mail.iniyanjoseph.com" ;;
    TXT) name="_dmarc.iniyanjoseph.com" ;;
  esac
  echo "-- $kind $name"
  if command -v dig >/dev/null 2>&1; then
    dig +short "$name" "$kind" | head -n 12 || true
  elif command -v getent >/dev/null 2>&1 && [[ "$kind" == "A" ]]; then
    getent ahostsv4 "$name" || true
  else
    echo "Install bind/dig to inspect this DNS record."
  fi
done
if command -v dig >/dev/null 2>&1; then
  echo "-- SPF (existing TXT at apex; inspect before changing!)"
  dig +short TXT iniyanjoseph.com | head -n 20 || true
  echo "-- Reverse DNS"
  dig +short -x 213.199.55.255 || true
fi

echo
echo "== Existing listeners (25, 465, 587, 993, 8081) =="
if command -v ss >/dev/null 2>&1; then
  ss -ltnp | grep -E ':(25|465|587|993|8081)[[:space:]]' || true
else
  echo "ss not installed."
fi

echo
echo "== Free disk space and running services =="
df -h /var/lib
for svc in mautrix-discord matrix-synapse mautrix-whatsapp nextcloud stalwart matrimail; do
  echo "$svc: $(systemctl is-active "$svc" 2>/dev/null || true)"
done

echo
echo "This script did not change anything."
echo "EXTERNAL SMTP port 25 accessibility and delivery reputation are NOT verified here."
