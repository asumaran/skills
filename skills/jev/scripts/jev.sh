#!/usr/bin/env bash
# Ask Jev (TypeSafe System One model) via OpenRouter's Decisions endpoint.
#
# Usage: jev.sh < request.json
#   request.json: {"state": ..., "questions": {...}}  ("model" is optional)
#
# Prints the raw response JSON on stdout plus a "_client" object with the
# wall-clock latency. On failure prints the HTTP status and the exact error
# body on stderr and exits non-zero.
#
# The OpenRouter key is read from the macOS Keychain (service
# "openrouter-api-key") and passed to curl through a config on stdin, so it
# never appears in argv, env, files, or output.
set -euo pipefail

ENDPOINT="${JEV_ENDPOINT:-https://openrouter.ai/api/alpha/decisions}"
MODEL="${JEV_MODEL:-typesafe/jev-1.13}"
KEYCHAIN_SERVICE="${JEV_KEYCHAIN_SERVICE:-openrouter-api-key}"

command -v jq >/dev/null || { echo "jev: jq is required" >&2; exit 2; }

key="$(security find-generic-password -s "$KEYCHAIN_SERVICE" -w 2>/dev/null)" && [[ -n "$key" ]] || {
  echo "jev: no key in Keychain (service '$KEYCHAIN_SERVICE')." >&2
  echo "     Store it with: security add-generic-password -U -a \"\$USER\" -s $KEYCHAIN_SERVICE -w" >&2
  exit 2
}

body="$(jq -c --arg m "$MODEL" '.model //= $m')" || { echo "jev: request is not valid JSON" >&2; exit 2; }

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

meta="$(
  printf 'header = "Authorization: Bearer %s"\n' "$key" |
    curl -sS -K - -X POST "$ENDPOINT" \
      -H 'Content-Type: application/json' \
      --data-binary "$body" \
      -o "$tmp" -w '%{http_code} %{time_total}'
)"
unset key

status="${meta%% *}"
elapsed="${meta##* }"

if [[ "$status" != 2* ]]; then
  echo "jev: HTTP $status after ${elapsed}s" >&2
  cat "$tmp" >&2
  echo >&2
  exit 1
fi

jq --argjson t "$elapsed" '. + {_client: {elapsed_seconds: $t}}' "$tmp"
