#!/bin/bash
set -euo pipefail

PORT="${1:-8501}"
APP_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
LOG="/tmp/medsync8-streamlit.log"

export SUPABASE_URL="${SUPABASE_URL:-https://test.supabase.co}"
export SUPABASE_KEY="${SUPABASE_KEY:-test-key-placeholder}"
export STRIPE_PAYMENT_LINK="${STRIPE_PAYMENT_LINK:-https://buy.stripe.com/test}"

cleanup() {
  if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "=== Installing dependencies ==="
pip install -q -r "$APP_DIR/requirements.txt" 2>&1 | tail -1
pip install -q pytest 2>&1 | tail -1

echo "=== Running unit tests ==="
(cd "$APP_DIR" && python -m pytest tests/ -v) || { echo "FAIL: tests"; exit 1; }

echo "=== Starting Streamlit on port $PORT ==="
(cd "$APP_DIR" && streamlit run med_sync_app_with_stripe.py \
  --server.port "$PORT" \
  --server.headless true \
  --server.address 0.0.0.0 \
  --browser.gatherUsageStats false \
  > "$LOG" 2>&1) &
PID=$!

echo "=== Waiting for server ==="
for i in $(seq 1 15); do
  if curl -s -o /dev/null -w '' "http://localhost:$PORT/_stcore/health" 2>/dev/null; then
    break
  fi
  sleep 1
done

HEALTH=$(curl -s "http://localhost:$PORT/_stcore/health" 2>/dev/null || echo "UNREACHABLE")
if [ "$HEALTH" != "ok" ]; then
  echo "FAIL: health check returned '$HEALTH'"
  cat "$LOG"
  exit 1
fi
echo "Health: $HEALTH"

echo "=== Checking main page ==="
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$PORT/")
if [ "$HTTP_CODE" != "200" ]; then
  echo "FAIL: main page returned HTTP $HTTP_CODE"
  exit 1
fi
echo "Main page: HTTP $HTTP_CODE"

echo "=== Checking host config ==="
curl -s "http://localhost:$PORT/_stcore/host-config" | python -m json.tool > /dev/null
echo "Host config: valid JSON"

echo "=== Stopping server ==="
kill "$PID" 2>/dev/null || true
wait "$PID" 2>/dev/null || true

echo ""
echo "ALL CHECKS PASSED"
