#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${PLUTO_PORT:-8080}"
HOST="${PLUTO_HOST:-0.0.0.0}"
PYTHON="${PLUTO_PYTHON:-/home/pi/yolo/env/bin/python}"

SONG="${PLUTO_DANCE_AUDIO:-}"
if [[ -z "$SONG" ]]; then
  for candidate in \
    "$ROOT/audio/Michael_Jackson_-_Billie_Jean_This_is_it_2009_(mp3.pm).mp3" \
    "/home/pi/Downloads/Michael_Jackson_-_Billie_Jean_This_is_it_2009_(mp3.pm).mp3"
  do
    if [[ -f "$candidate" ]]; then
      SONG="$candidate"
      break
    fi
  done
fi

if [[ -n "$SONG" ]]; then
  export PLUTO_DANCE_AUDIO="$SONG"
  echo "PLUTO_DANCE_AUDIO=$PLUTO_DANCE_AUDIO"
else
  echo "WARNING: dance audio file not found. Copy it to:"
  echo "  $ROOT/audio/Michael_Jackson_-_Billie_Jean_This_is_it_2009_(mp3.pm).mp3"
fi

exec "$PYTHON" -m pluto_runtime.web_shell \
  --host "$HOST" \
  --port "$PORT" \
  --camera-device /dev/video0 \
  --camera-resolution 320x320 \
  --camera-stream-fps 8 \
  --camera-frame-skip 1 \
  --camera-detection-hold 2.0 \
  --camera-confidence 0.30 \
  --wave-pose-frame-skip 1 \
  --wave-pose-max-tracks 2 \
  --microphone-device plughw:CARD=camera,DEV=0 \
  --speaker-device Headphones
