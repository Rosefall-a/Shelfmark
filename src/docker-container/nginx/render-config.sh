#!/bin/sh
set -eu

output="${1:-/etc/nginx/ready.conf}"
enabled="${NGINX_TLS_ENABLED:-false}"
redirect="${NGINX_TLS_REDIRECT_HTTP:-false}"
cert="${NGINX_TLS_CERTIFICATE:-/etc/nginx/tls/tls.crt}"
key="${NGINX_TLS_PRIVATE_KEY:-/etc/nginx/tls/tls.key}"

case "$enabled" in
  true|TRUE|1|yes|YES) enabled=true ;;
  false|FALSE|0|no|NO|"") enabled=false ;;
  *) printf '%s\n' "Invalid NGINX_TLS_ENABLED value; use true or false." >&2; exit 1 ;;
esac
case "$redirect" in
  true|TRUE|1|yes|YES) redirect=true ;;
  false|FALSE|0|no|NO|"") redirect=false ;;
  *) printf '%s\n' "Invalid NGINX_TLS_REDIRECT_HTTP value; use true or false." >&2; exit 1 ;;
esac

if [ "$redirect" = true ] && [ "$enabled" != true ]; then
  printf '%s\n' "NGINX_TLS_REDIRECT_HTTP requires NGINX_TLS_ENABLED=true." >&2
  exit 1
fi

if [ "$enabled" = true ]; then
  if [ ! -f "$cert" ]; then printf '%s\n' "TLS is enabled but certificate file is missing: $cert" >&2; exit 1; fi
  if [ ! -f "$key" ]; then printf '%s\n' "TLS is enabled but private key file is missing: $key" >&2; exit 1; fi
  if [ ! -r "$cert" ]; then printf '%s\n' "TLS certificate is not readable: $cert" >&2; exit 1; fi
  if [ ! -r "$key" ]; then printf '%s\n' "TLS private key is not readable: $key" >&2; exit 1; fi

  sed -e "s#ssl_certificate /etc/nginx/tls/tls.crt;#ssl_certificate $cert;#" \
      -e "s#ssl_certificate_key /etc/nginx/tls/tls.key;#ssl_certificate_key $key;#" \
      /etc/nginx/ready.conf > "$output"
else
  awk '
    /listen 443 ssl;/ { tls=1 }
    tls && /^    }/ { tls=0; next }
    !tls { print }
  ' /etc/nginx/ready.conf > "$output"
fi

if [ "$redirect" = true ]; then
  sed -i '/listen 80;/a\        if ($scheme = http) { return 301 https://$host$request_uri; }' "$output"
fi
