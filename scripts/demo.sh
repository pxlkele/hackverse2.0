#!/usr/bin/env bash
#
# One command that brings the demo up and keeps it up.
#
#     ./scripts/demo.sh
#
# Starts the API and a cloudflared tunnel, prints the public URL, then watches
# the tunnel and rebuilds it when it dies. Quick tunnels die on their own -
# twice in one afternoon during this build - and when one does, the phone shows
# "cannot reach the server" while the backend is perfectly healthy on
# localhost. This turns that from a debugging session into a line of output.
#
# The URL still changes when a tunnel is rebuilt: a *stable* address needs a
# named tunnel, which needs a Cloudflare account and a domain. What this buys
# is that the new URL appears here within seconds instead of being discovered
# by a person tapping a dead button.
#
# The live URL is always in scripts/CURRENT_URL.txt while this is running.
#
# Ctrl-C stops both processes.

set -uo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8000}"
URL_FILE="scripts/CURRENT_URL.txt"
TUNNEL_LOG="$(mktemp -t setu-tunnel)"
CHECK_EVERY="${CHECK_EVERY:-20}"

# Skip the 2.4GB vision model unless asked for it. See _warm_models in
# services/api/main.py: holding it resident alongside Whisper and Granite is
# what makes response times swing from 6s to 50s on the same input.
export SETU_WARM="${SETU_WARM:-voice}"

API_PID=""
TUNNEL_PID=""

cleanup() {
  echo
  echo "stopping..."
  [ -n "$TUNNEL_PID" ] && kill "$TUNNEL_PID" 2>/dev/null
  [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null
  rm -f "$URL_FILE"
  exit 0
}
trap cleanup INT TERM

start_tunnel() {
  [ -n "$TUNNEL_PID" ] && kill "$TUNNEL_PID" 2>/dev/null
  pkill -f "cloudflared tunnel --url http://localhost:$PORT" 2>/dev/null
  sleep 2
  : > "$TUNNEL_LOG"
  cloudflared tunnel --url "http://localhost:$PORT" > "$TUNNEL_LOG" 2>&1 &
  TUNNEL_PID=$!

  # cloudflared prints the hostname a second or two after it starts.
  for _ in $(seq 1 30); do
    sleep 1
    URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$TUNNEL_LOG" | head -1)
    [ -n "$URL" ] && break
  done

  if [ -z "${URL:-}" ]; then
    echo "!! cloudflared did not report a URL. Its output:"
    tail -5 "$TUNNEL_LOG"
    return 1
  fi

  echo "$URL" > "$URL_FILE"
  echo
  echo "  ┌────────────────────────────────────────────────────────────"
  echo "  │  PHONE:  $URL/pwa/"
  echo "  │  IVR:    $URL/"
  echo "  └────────────────────────────────────────────────────────────"
  echo "  (reload the page on the phone once after a new URL)"
  echo
}

# ── API ──────────────────────────────────────────────────────────────────────
if curl -s -o /dev/null --max-time 3 "http://127.0.0.1:$PORT/api/health"; then
  echo "API already running on :$PORT - leaving it alone"
else
  echo "starting API on :$PORT (SETU_WARM=$SETU_WARM)..."
  .venv/bin/uvicorn services.api.main:app --host 0.0.0.0 --port "$PORT" \
    > /tmp/setu-api.log 2>&1 &
  API_PID=$!
  for _ in $(seq 1 60); do
    sleep 2
    curl -s -o /dev/null --max-time 3 "http://127.0.0.1:$PORT/api/health" && break
  done
fi

# Warming keeps running in the background after health goes green, and requests
# made during it measure several times slower. Wait it out here rather than
# have someone time a cold request and conclude the app is slow.
echo "warming models (about a minute) - do not time anything yet..."
sleep 45
echo "warm."

start_tunnel

# ── watch ────────────────────────────────────────────────────────────────────
while true; do
  sleep "$CHECK_EVERY"

  if ! curl -s -o /dev/null --max-time 3 "http://127.0.0.1:$PORT/api/health"; then
    echo "!! API is not answering on localhost. Check /tmp/setu-api.log"
    continue
  fi

  # The process staying alive means nothing: a dead quick tunnel keeps running
  # and simply stops routing, which is exactly how this was missed for an hour.
  CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "$(cat "$URL_FILE")/api/health")
  if [ "$CODE" != "200" ]; then
    echo "!! tunnel stopped routing (got '$CODE') - rebuilding"
    start_tunnel
  fi
done
