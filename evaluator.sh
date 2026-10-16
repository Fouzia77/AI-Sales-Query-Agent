#!/usr/bin/env bash
set -u
BASE_URL="${BASE_URL:-http://localhost:8000}"

# Wait up to about 2 minutes for the service.
ready=0
for attempt in $(seq 1 24); do
  if curl --silent --show-error --fail "$BASE_URL/health" >/dev/null 2>&1; then
    ready=1
    break
  fi
  printf '.'
  sleep 5
done
printf '\n'
if [ "$ready" -ne 1 ]; then
  echo "ERROR: API did not become ready at $BASE_URL" >&2
  exit 1
fi

echo "API is up. Running end-to-end sales questions..."
queries=(
  "Top 3 customers by order count"
  "Average order value by region"
  "Monthly revenue for 2024"
  "Products that have never been ordered"
  "Total spend by customer segment"
)
SUCCESS_COUNT=0
for q in "${queries[@]}"; do
  echo "Testing: $q"
  payload=$(python -c 'import json,sys; print(json.dumps({"question":sys.argv[1]}))' "$q")
  response=$(curl --silent --show-error --fail -X POST "$BASE_URL/query" -H 'Content-Type: application/json' -d "$payload") || response='{}'
  if printf '%s' "$response" | python -c 'import json,sys; d=json.load(sys.stdin); assert isinstance(d.get("results"), list) and len(d["results"]) > 0' >/dev/null 2>&1; then
    echo "  PASS"
    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
  else
    echo "  FAIL: response was $response"
  fi
done

echo "$SUCCESS_COUNT / ${#queries[@]} queries succeeded."
if [ "$SUCCESS_COUNT" -ne "${#queries[@]}" ]; then exit 1; fi
