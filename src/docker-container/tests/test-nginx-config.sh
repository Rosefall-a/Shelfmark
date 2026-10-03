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

rendered="$work/http-defaults.conf"
"$render" /etc/nginx/ready.conf "$rendered"
grep -q 'real_ip_header X-Forwarded-For;' "$rendered"
grep -q 'real_ip_recursive on;' "$rendered"
grep -q 'set_real_ip_from 10.0.0.0/8;' "$rendered"
grep -q 'set_real_ip_from 100.64.0.0/10;' "$rendered"
grep -q 'set_real_ip_from fc00::/7;' "$rendered"
grep -q 'set_real_ip_from 173.245.48.0/20;' "$rendered"
grep -q 'set_real_ip_from 2606:4700::/32;' "$rendered"
nginx -t -c "$rendered"

rendered="$work/http.conf"
NGINX_REALIP_TRUSTED_PROXIES="10.0.0.0/8 192.0.2.0/24" "$render" /etc/nginx/ready.conf "$rendered"
! grep -q 'listen 443 ssl;' "$rendered"
grep -q 'real_ip_header X-Forwarded-For;' "$rendered"
grep -q 'real_ip_recursive on;' "$rendered"
grep -q 'set_real_ip_from 10.0.0.0/8;' "$rendered"
grep -q 'set_real_ip_from 192.0.2.0/24;' "$rendered"
if grep -q 'set_real_ip_from 127.0.0.0/8;' "$rendered"; then
  echo "default realip trust leaked into an explicit override" >&2
  exit 1
fi
nginx -t -c "$rendered"

NGINX_REALIP_HEADER=CF-Connecting-IP NGINX_REALIP_TRUSTED_PROXIES="" "$render" /etc/nginx/ready.conf "$work/realip-disabled.conf"
grep -q 'real_ip_header CF-Connecting-IP;' "$work/realip-disabled.conf"
grep -q 'real_ip_recursive on;' "$work/realip-disabled.conf"
if grep -q 'set_real_ip_from ' "$work/realip-disabled.conf"; then
  echo "empty trusted-proxy override unexpectedly rendered a trusted source" >&2
  exit 1
fi
nginx -t -c "$work/realip-disabled.conf"

if NGINX_REALIP_HEADER='bad;include /tmp/evil;' "$render" /etc/nginx/ready.conf "$work/invalid-realip-header.conf"; then
  echo "invalid realip header unexpectedly succeeded" >&2
  exit 1
fi

if NGINX_REALIP_TRUSTED_PROXIES='10.0.0.0/8;include /tmp/evil;' "$render" /etc/nginx/ready.conf "$work/invalid-realip-proxies.conf"; then
  echo "invalid realip proxy list unexpectedly succeeded" >&2
  exit 1
fi

rendered="$work/https.conf"
NGINX_TLS_ENABLED=true NGINX_TLS_CERTIFICATE="$work/tls/cert.pem" NGINX_TLS_PRIVATE_KEY="$work/tls/key.pem" "$render" /etc/nginx/readytls.conf "$rendered"
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
  NGINX_TLS_PRIVATE_KEY="$work/tls/key.pem" "$render" /etc/nginx/readytls.conf "$work/missing-cert.conf"; then
  echo "missing certificate unexpectedly succeeded" >&2
  exit 1
fi

if NGINX_TLS_ENABLED=true NGINX_TLS_CERTIFICATE="$work/tls/cert.pem" \
  NGINX_TLS_PRIVATE_KEY="$work/tls/missing.pem" "$render" /etc/nginx/readytls.conf "$work/missing-key.conf"; then
  echo "missing private key unexpectedly succeeded" >&2
  exit 1
fi

printf '%s\n' 'not a certificate' > "$work/tls/invalid.pem"
NGINX_TLS_ENABLED=true \
NGINX_TLS_CERTIFICATE="$work/tls/invalid.pem" \
NGINX_TLS_PRIVATE_KEY="$work/tls/key.pem" "$render" /etc/nginx/readytls.conf "$work/invalid-cert.conf"
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
  NGINX_TLS_PRIVATE_KEY="$work/tls/invalid-key.pem" "$render" /etc/nginx/readytls.conf "$work/invalid-key.conf" \
  && nginx -t -c "$work/invalid-key.conf" >/dev/null 2>&1; then
  echo "invalid private key unexpectedly passed nginx validation" >&2
  exit 1
fi

openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
  -keyout "$work/tls/other-key.pem" -out "$work/tls/other-cert.pem" \
  -subj "/CN=other" >/dev/null 2>&1
NGINX_TLS_ENABLED=true \
NGINX_TLS_CERTIFICATE="$work/tls/cert.pem" \
NGINX_TLS_PRIVATE_KEY="$work/tls/other-key.pem" "$render" /etc/nginx/readytls.conf "$work/mismatched.conf"
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
