#!/bin/sh
set -eu

source="${1:-/etc/nginx/ready.conf}"
output="${2:-/etc/nginx/ready.conf}"
enabled="${NGINX_TLS_ENABLED:-false}"
redirect="${NGINX_TLS_REDIRECT_HTTP:-false}"
cert="${NGINX_TLS_CERTIFICATE:-}"
key="${NGINX_TLS_PRIVATE_KEY:-}"
realip_header="${NGINX_REALIP_HEADER:-X-Forwarded-For}"
default_trusted_proxies="127.0.0.0/8 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16 100.64.0.0/10 ::1/128 fc00::/7 fe80::/10 103.21.244.0/22 103.22.200.0/22 103.31.4.0/22 104.16.0.0/13 104.24.0.0/14 108.162.192.0/18 131.0.72.0/22 141.101.64.0/18 162.158.0.0/15 172.64.0.0/13 173.245.48.0/20 188.114.96.0/20 190.93.240.0/20 197.234.240.0/22 198.41.128.0/17 2400:cb00::/32 2606:4700::/32 2803:f800::/32 2405:b500::/32 2405:8100::/32 2a06:98c0::/29 2c0f:f248::/32"
if [ "${NGINX_REALIP_TRUSTED_PROXIES+x}" = x ]; then
  trusted_proxies="$NGINX_REALIP_TRUSTED_PROXIES"
else
  trusted_proxies="$default_trusted_proxies"
fi
generated_dir="/run/unnamed-tracking/tls"
tmp_output="${output}.tmp.$$"
realip_tmp="${output}.realip.$$"

cleanup() {
  rm -f "$tmp_output" "$realip_tmp"
}
trap cleanup EXIT INT TERM

case "$realip_header" in
  ''|*[!A-Za-z0-9_-]*)
    printf '%s\n' "Invalid NGINX_REALIP_HEADER value; use an HTTP header name." >&2
    exit 1
    ;;
esac

for proxy in $trusted_proxies; do
  case "$proxy" in
    unix:|*[!0-9A-Fa-f:./]*)
      if [ "$proxy" != "unix:" ]; then
        printf '%s\n' "Invalid NGINX_REALIP_TRUSTED_PROXIES entry: $proxy" >&2
        exit 1
      fi
      ;;
  esac
done

{
  printf '%s\n' "    # Trusted proxy configuration rendered from NGINX_REALIP_* environment."
  printf '    real_ip_header %s;\n' "$realip_header"
  printf '%s\n' "    real_ip_recursive on;"
  for proxy in $trusted_proxies; do
    printf '    set_real_ip_from %s;\n' "$proxy"
  done
} > "$realip_tmp"

awk -v snippet="$realip_tmp" '
  BEGIN { inserted = 0 }
  !inserted && $0 ~ /^[[:space:]]*server[[:space:]]*\{/ {
    while ((getline line < snippet) > 0) print line
    close(snippet)
    inserted = 1
  }
  { print }
' "$source" > "${tmp_output}.base"

if [ "$enabled" = "true" ]; then
  default_cert="/etc/nginx/tls/tls.crt"
  default_key="/etc/nginx/tls/tls.key"

  if [ -z "$cert" ] && [ -z "$key" ]; then
    if [ -s "$default_cert" ] && [ -s "$default_key" ]; then
      cert="$default_cert"
      key="$default_key"
    else
      cert="$generated_dir/tls.crt"
      key="$generated_dir/tls.key"
    fi
  elif [ -z "$cert" ] || [ -z "$key" ]; then
    printf '%s\n' "NGINX_TLS_CERTIFICATE and NGINX_TLS_PRIVATE_KEY must be supplied together." >&2
    exit 1
  elif [ "$cert" = "$default_cert" ] && [ "$key" = "$default_key" ] &&
       { [ ! -s "$cert" ] || [ ! -s "$key" ]; }; then
    cert="$generated_dir/tls.crt"
    key="$generated_dir/tls.key"
  fi

  if [ "$cert" = "$generated_dir/tls.crt" ] && [ "$key" = "$generated_dir/tls.key" ] &&
     { [ ! -s "$cert" ] || [ ! -s "$key" ]; }; then
    printf '%s\n' "No usable TLS certificate/private key supplied; generating a self-signed certificate for localhost." >&2
    mkdir -p "$generated_dir"
    umask 077
    openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
      -keyout "$key" -out "$cert" \
      -subj "/CN=localhost" \
      -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" >/dev/null 2>&1
    chmod 0644 "$cert"
    chmod 0600 "$key"
  fi
  if [ ! -f "$cert" ]; then printf '%s\n' "TLS certificate file is missing: $cert" >&2; exit 1; fi
  if [ ! -f "$key" ]; then printf '%s\n' "TLS private key file is missing: $key" >&2; exit 1; fi
  if [ ! -r "$cert" ]; then printf '%s\n' "TLS certificate is not readable: $cert" >&2; exit 1; fi
  if [ ! -r "$key" ]; then printf '%s\n' "TLS private key is not readable: $key" >&2; exit 1; fi
  sed -e "s#ssl_certificate /etc/nginx/tls/tls.crt;#ssl_certificate $cert;#" \
      -e "s#ssl_certificate_key /etc/nginx/tls/tls.key;#ssl_certificate_key $key;#" \
      "${tmp_output}.base" > "$tmp_output"
else
  cat "${tmp_output}.base" > "$tmp_output"
fi

rm -f "${tmp_output}.base"
mv "$tmp_output" "$output"
trap - EXIT INT TERM
