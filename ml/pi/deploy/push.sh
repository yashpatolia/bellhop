#!/usr/bin/env bash
# Mac: sync ml/pi to the Pi and restart the units.  PI_HOST=pi@bellhop.local bash deploy/push.sh
set -eu
if [ -z "${PI_HOST:-}" ]; then
  echo "refusing to run: set PI_HOST (e.g. PI_HOST=pi@bellhop.local)" >&2
  exit 1
fi
REMOTE_DIR="${REMOTE_DIR:-ml}"            # relative to the Pi user's home: /home/pi/ml
UNITS="${UNITS:-bellhop-drive bellhop-speech bellhop-vision}"
cd "$(dirname "$0")/.."
rsync -az --delete \
  --exclude '/.venv' --exclude '__pycache__' --exclude '*.pyc' --exclude '.env' --exclude '.python-version' \
  --exclude '.pytest_cache' --exclude '.ruff_cache' --exclude '/models' --exclude '.cache' \
  ./ "$PI_HOST:$REMOTE_DIR/"
# shellcheck disable=SC2086
ssh "$PI_HOST" "sudo systemctl restart $UNITS && systemctl --no-pager is-active $UNITS"
