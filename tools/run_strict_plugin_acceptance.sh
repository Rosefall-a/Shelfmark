#!/usr/bin/env bash
# Exercise installed plugins with the production toolchain and strict bwrap.
set -euo pipefail

workspace=$(realpath "${GITHUB_WORKSPACE:?Run this helper on a disposable CI runner}")
host_root=$(realpath "$1")
plugins_root=$(realpath "$2")
work_root=$(realpath -m "$3")
runner_temp=$(realpath "${RUNNER_TEMP:?}")
case "$host_root" in "$workspace"|"$workspace/"*) ;; *) exit 2 ;; esac
case "$plugins_root" in "$workspace"|"$workspace/"*) ;; *) exit 2 ;; esac
case "$work_root" in "$runner_temp/"*) ;; *) exit 2 ;; esac
[ ! -e "$work_root" ] || exit 2
context=$(mktemp -d "$runner_temp/strict-plugin-build.XXXXXX")
mkdir "$context/host" "$context/plugins" "$context/evidence" "$work_root"
# The capability-free container cannot override the runner-owned directory mode.
chmod 0777 "$context/evidence"
# Archives exclude checkout credentials, untracked files and the runner's home.
git -C "$host_root" archive HEAD | tar -x -C "$context/host"
git -C "$plugins_root" archive HEAD | tar -x -C "$context/plugins"
cat > "$context/Dockerfile" <<'DOCKERFILE'
FROM node:24-bookworm-slim AS node
FROM python:3.12-slim-bookworm
COPY --from=node /usr/local/ /usr/local/
RUN apt-get update -qq && apt-get install -y --no-install-recommends bubblewrap git libpq5
COPY host /workspace/host
COPY plugins /workspace/plugins
RUN python -m pip install -r /workspace/host/src/backend/requirements.txt -r /workspace/plugins/requirements-dev.txt
RUN cd /workspace/host/src/frontend && npm ci
RUN cd /workspace/plugins && npm ci && npx playwright install --with-deps chromium --only-shell
WORKDIR /workspace/plugins
DOCKERFILE
cleanup_image() {
  if [ -f "$context/image.id" ]; then
    image_id=$(cat "$context/image.id")
    case "$image_id" in sha256:*) docker image rm "$image_id" >/dev/null || true ;; esac
  fi
}
trap cleanup_image EXIT
docker build --iidfile "$context/image.id" "$context"
image_id=$(cat "$context/image.id")
# Only the disposable evidence directory is mounted. There is no host network,
# Docker socket or runner checkout/cache mount. SETFCAP permits the kernel's root
# UID mapping check; bwrap drops it before running plugin code in its namespace.
# The container's masked proc entries would prevent a nested private proc mount.
# These container-scoped filters must permit bwrap to create its own namespaces;
# bwrap still applies the full production filesystem/network/resource boundaries.
status=0
docker run --rm --cap-drop ALL --cap-add SETFCAP --security-opt no-new-privileges \
  --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
  --security-opt systempaths=unconfined \
  --add-host test-database:host-gateway \
  --volume "$context/evidence:/evidence" \
  --env POSTGRES_USER --env POSTGRES_PASSWORD --env POSTGRES_PORT \
  --env POSTGRES_DB --env SECRET_KEY --env POSTGRES_HOST=test-database \
  --env PYTHONPATH=/workspace/host/src/backend \
  "$image_id" bash -euc '
    bwrap --unshare-all --cap-drop ALL \
      --ro-bind /usr /usr --ro-bind /bin /bin --ro-bind /lib /lib \
      --ro-bind /lib64 /lib64 --dev /dev --proc /proc -- /bin/true
    python tools/check_jellyfin_official_lifecycle.py \
      --host-root /workspace/host --work-root /evidence/run --browser
  ' || status=$?
if [ -d "$context/evidence/run" ]; then
  find "$context/evidence/run" -maxdepth 1 -type f \
    \( -name '*.log' -o -name conformance.json \) -exec cp {} "$work_root/" \;
  if [ -d "$context/evidence/run/screenshots" ]; then
    cp -R "$context/evidence/run/screenshots" "$work_root/"
  fi
fi
exit "$status"
