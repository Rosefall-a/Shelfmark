#!/bin/sh
set -eu

render=/usr/local/bin/render-production-nginx
base=/etc/nginx/ready.conf
work=/tmp/nginx-config-tests
rm -rf "$work"
mkdir -p "$work/tls"

openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
  -keyout "$work/tls/key.pem" -out "$work/tls/cert.pem" \
  -subj "/CN=localhost" >/dev/null 2>&1

rendered="$work/http.conf"
cp "$base" "$rendered"
! grep -q 'listen 443 ssl;' "$rendered"
nginx -t -c "$rendered"

rendered="$work/https.conf"
NGINX_TLS_ENABLED=true NGINX_TLS_CERTIFICATE="$work/tls/cert.pem" NGINX_TLS_PRIVATE_KEY="$work/tls/key.pem" "$render" "$base" "$rendered"
grep -q 'listen 443 ssl;' "$rendered"
grep -q "ssl_certificate $work/tls/cert.pem;" "$rendered"
grep -q "ssl_certificate_key $work/tls/key.pem;" "$rendered"
nginx -t -c "$rendered"

rendered="$work/https-redirect.conf"
NGINX_TLS_ENABLED=true NGINX_TLS_REDIRECT_HTTP=true NGINX_TLS_CERTIFICATE="$work/tls/cert.pem" NGINX_TLS_PRIVATE_KEY="$work/tls/key.pem" "$render" /etc/nginx/readytlsredirect.conf "$rendered"
grep -q 'listen 443 ssl;' "$rendered"
grep -q 'return 301 https://$host$request_uri;' "$rendered"
nginx -t -c "$rendered"

rm -rf /run/unnamed-tracking/tls
NGINX_TLS_ENABLED=true "$render" /etc/nginx/readytls.conf "$work/generated.conf"
test -s /run/unnamed-tracking/tls/tls.crt
test -s /run/unnamed-tracking/tls/tls.key
openssl x509 -in /run/unnamed-tracking/tls/tls.crt -noout -subject >/dev/null
grep -q 'ssl_certificate /run/unnamed-tracking/tls/tls.crt;' "$work/generated.conf"
nginx -t -c "$work/generated.conf"

rm -rf /etc/nginx/tls
NGINX_TLS_ENABLED=true NGINX_TLS_CERTIFICATE=/etc/nginx/tls/tls.crt NGINX_TLS_PRIVATE_KEY=/etc/nginx/tls/tls.key "$render" /etc/nginx/readytls.conf "$work/default-path-fallback.conf"
grep -q 'ssl_certificate /run/unnamed-tracking/tls/tls.crt;' "$work/default-path-fallback.conf"
grep -q 'ssl_certificate_key /run/unnamed-tracking/tls/tls.key;' "$work/default-path-fallback.conf"
nginx -t -c "$work/default-path-fallback.conf"

cp /etc/nginx/readytls.conf "$work/in-place.conf"
NGINX_TLS_ENABLED=true "$render" "$work/in-place.conf" "$work/in-place.conf"
grep -q 'listen 443 ssl;' "$work/in-place.conf"
grep -q 'ssl_certificate /run/unnamed-tracking/tls/tls.crt;' "$work/in-place.conf"
nginx -t -c "$work/in-place.conf"

if NGINX_TLS_ENABLED=true NGINX_TLS_CERTIFICATE="$work/tls/missing.pem" \
  NGINX_TLS_PRIVATE_KEY="$work/tls/key.pem" "$render" "$work/missing-cert.conf"; then
  echo "missing certificate unexpectedly succeeded" >&2
  exit 1
fi

if NGINX_TLS_ENABLED=true NGINX_TLS_CERTIFICATE="$work/tls/cert.pem" \
  NGINX_TLS_PRIVATE_KEY="$work/tls/missing.pem" "$render" "$work/missing-key.conf"; then
  echo "missing private key unexpectedly succeeded" >&2
  exit 1
fi

printf '%s\n' 'not a certificate' > "$work/tls/invalid.pem"
NGINX_TLS_ENABLED=true \
NGINX_TLS_CERTIFICATE="$work/tls/invalid.pem" \
NGINX_TLS_PRIVATE_KEY="$work/tls/key.pem" "$render" "$work/invalid-cert.conf"
if nginx -t -c "$work/invalid-cert.conf" >/dev/null 2>&1; then
  echo "invalid certificate unexpectedly passed nginx validation" >&2
  exit 1
fi

if NGINX_TLS_ENABLED=maybe "$render" "$work/invalid-env.conf"; then
  echo "invalid TLS enabled value unexpectedly succeeded" >&2
  exit 1
fi
if NGINX_TLS_ENABLED=false NGINX_TLS_REDIRECT_HTTP=true "$render" "$work/invalid-redirect.conf"; then
  echo "HTTP redirect unexpectedly succeeded while TLS was disabled" >&2
  exit 1
fi


printf '%s\n' 'not a private key' > "$work/tls/invalid-key.pem"
if NGINX_TLS_ENABLED=true \
  NGINX_TLS_CERTIFICATE="$work/tls/cert.pem" \
  NGINX_TLS_PRIVATE_KEY="$work/tls/invalid-key.pem" "$render" "$work/invalid-key.conf" \
  && nginx -t -c "$work/invalid-key.conf" >/dev/null 2>&1; then
  echo "invalid private key unexpectedly passed nginx validation" >&2
  exit 1
fi

openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
  -keyout "$work/tls/other-key.pem" -out "$work/tls/other-cert.pem" \
  -subj "/CN=other" >/dev/null 2>&1
NGINX_TLS_ENABLED=true \
NGINX_TLS_CERTIFICATE="$work/tls/cert.pem" \
NGINX_TLS_PRIVATE_KEY="$work/tls/other-key.pem" "$render" "$work/mismatched.conf"
if nginx -t -c "$work/mismatched.conf" >/dev/null 2>&1; then
  echo "mismatched certificate/key unexpectedly passed nginx validation" >&2
  exit 1
fi

grep -q 'X-Content-Type-Options "nosniff"' "$rendered"
grep -q 'Referrer-Policy "strict-origin-when-cross-origin"' "$rendered"
grep -q 'X-Frame-Options "SAMEORIGIN"' "$rendered"
grep -q 'X-Forwarded-Proto $scheme' "$rendered"
grep -q 'proxy_read_timeout 60s' "$rendered"

echo "production Nginx/TLS configuration tests passed"
