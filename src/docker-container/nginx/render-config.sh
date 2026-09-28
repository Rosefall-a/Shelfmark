#!/bin/sh
set -eu

source="${1:-/etc/nginx/ready.conf}"
output="${2:-/etc/nginx/ready.conf}"
enabled="${NGINX_TLS_ENABLED:-false}"
redirect="${NGINX_TLS_REDIRECT_HTTP:-false}"
cert="${NGINX_TLS_CERTIFICATE:-}"
key="${NGINX_TLS_PRIVATE_KEY:-}"
generated_dir="/run/unnamed-tracking/tls"
tmp_output="${output}.tmp.$$"

cleanup() {
  rm -f "$tmp_output"
}
trap cleanup EXIT INT TERM

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
      "$source" > "$tmp_output"
else
  cat "$source" > "$tmp_output"
fi

mv "$tmp_output" "$output"
trap - EXIT INT TERM