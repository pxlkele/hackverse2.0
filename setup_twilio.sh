#!/usr/bin/env bash
# ── Setu — wire the real phone number in 3 steps ──────────────────────────
# Run this ONCE after filling in your Twilio credentials.
# Usage:  bash setup_twilio.sh

set -euo pipefail

# ── 1. check .env has the credentials ────────────────────────────────────────
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example — fill in your Twilio credentials first."
  exit 1
fi

source .env

if [[ -z "${TWILIO_ACCOUNT_SID:-}" || "${TWILIO_ACCOUNT_SID}" == "your_sid_here" ]]; then
  echo "ERROR: Set TWILIO_ACCOUNT_SID in .env first."
  exit 1
fi
if [[ -z "${TWILIO_AUTH_TOKEN:-}" || "${TWILIO_AUTH_TOKEN}" == "your_token_here" ]]; then
  echo "ERROR: Set TWILIO_AUTH_TOKEN in .env first."
  exit 1
fi
if [[ -z "${TWILIO_PHONE_NUMBER:-}" || "${TWILIO_PHONE_NUMBER}" == "+1234567890" ]]; then
  echo "ERROR: Set TWILIO_PHONE_NUMBER in .env first (e.g. +17372212163)."
  exit 1
fi

# ── 2. start ngrok and get the public URL ────────────────────────────────────
echo ""
echo "Starting ngrok tunnel on port 8000…"
ngrok http 8000 --log=stdout &
NGROK_PID=$!
sleep 3

NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | python3 -c \
  "import sys,json; t=json.load(sys.stdin)['tunnels']; print(next(x['public_url'] for x in t if x['proto']=='https'))")

if [[ -z "$NGROK_URL" ]]; then
  echo "ERROR: Could not get ngrok URL. Is ngrok installed? (brew install ngrok)"
  kill $NGROK_PID 2>/dev/null || true
  exit 1
fi

echo "Public URL: $NGROK_URL"

# ── 3. set the webhook on the Twilio number via REST API ─────────────────────
# Get the phone number SID first
NUMBER_SID=$(curl -s -X GET \
  "https://api.twilio.com/2010-04-01/Accounts/${TWILIO_ACCOUNT_SID}/IncomingPhoneNumbers.json?PhoneNumber=${TWILIO_PHONE_NUMBER}" \
  -u "${TWILIO_ACCOUNT_SID}:${TWILIO_AUTH_TOKEN}" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['incoming_phone_numbers'][0]['sid'])")

if [[ -z "$NUMBER_SID" ]]; then
  echo "ERROR: Could not find phone number ${TWILIO_PHONE_NUMBER} in your account."
  kill $NGROK_PID 2>/dev/null || true
  exit 1
fi

# Set the voice webhook
curl -s -X POST \
  "https://api.twilio.com/2010-04-01/Accounts/${TWILIO_ACCOUNT_SID}/IncomingPhoneNumbers/${NUMBER_SID}.json" \
  -u "${TWILIO_ACCOUNT_SID}:${TWILIO_AUTH_TOKEN}" \
  -d "VoiceUrl=${NGROK_URL}/twilio/incoming" \
  -d "VoiceMethod=POST" \
  -d "StatusCallback=${NGROK_URL}/twilio/status" \
  -d "StatusCallbackMethod=POST" \
  > /dev/null

# Write PUBLIC_URL into .env so the webhook router picks it up
if grep -q "^PUBLIC_URL=" .env; then
  sed -i '' "s|^PUBLIC_URL=.*|PUBLIC_URL=${NGROK_URL}|" .env
else
  echo "PUBLIC_URL=${NGROK_URL}" >> .env
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ ngrok running:    $NGROK_URL"
echo "  ✓ Twilio webhook:   $NGROK_URL/twilio/incoming"
echo "  ✓ Phone number:     $TWILIO_PHONE_NUMBER"
echo ""
echo "  Now start the server:"
echo "    .venv/bin/uvicorn services.api.main:app --port 8000"
echo ""
echo "  Then dial $TWILIO_PHONE_NUMBER from any phone."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
