#!/usr/bin/env bash
# Read-only signature scan for Kafka incident logs.
# Exit 0: scan finished (including NO_HITS). Exit 2: usage or rg error.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATTERNS="${ROOT}/references/patterns.tsv"

if [[ $# -lt 1 ]]; then
  echo "usage: scan-kafka-logs.sh <file-or-dir>..." >&2
  exit 2
fi

if ! command -v rg >/dev/null 2>&1; then
  echo "rg is required" >&2
  exit 2
fi

for path in "$@"; do
  if [[ ! -e "$path" ]]; then
    echo "not found: $path" >&2
    exit 2
  fi
done

echo -e "id\tcount\tfirst_ts\tlast_ts\tsample"
any=0
err="$(mktemp)"
trap 'rm -f "$err"' EXIT

# Directory scans skip this skill's own text. Explicit files are still scanned,
# so the fixture tests keep working.
rg_glob=()
for path in "$@"; do
  if [[ -d "$path" ]]; then
    rg_glob=(
      --glob '!**/kafka-log-rca/SKILL.md'
      --glob '!**/kafka-log-rca/references/**'
      --glob '!**/kafka-log-rca/scripts/**'
      --glob '!**/kafka-log-rca/fixtures/**'
    )
    break
  fi
done

while IFS=$'\t' read -r id _case regex _note; do
  [[ -z "${id:-}" || "$id" == \#* ]] && continue
  [[ -z "${regex:-}" ]] && continue

  set +e
  matches="$(rg -z -n --no-heading "${rg_glob[@]}" -e "$regex" "$@" 2>"$err")"
  rc=$?
  set -e
  if [[ $rc -eq 2 ]]; then
    cat "$err" >&2
    exit 2
  fi
  if [[ $rc -eq 1 || -z "$matches" ]]; then
    continue
  fi

  count="$(printf '%s\n' "$matches" | wc -l | tr -d ' ')"
  timestamps="$(printf '%s\n' "$matches" | rg -o -e '\[[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9:.,]+\]' -e '[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9:.,]+' || true)"
  first_ts="$(printf '%s\n' "$timestamps" | head -n 1)"
  last_ts="$(printf '%s\n' "$timestamps" | tail -n 1)"
  sample="$(printf '%s\n' "$matches" | head -n 1 | tr '\t' ' ' | cut -c 1-180)"
  printf '%s\t%s\t%s\t%s\t%s\n' "$id" "$count" "$first_ts" "$last_ts" "$sample"
  any=1
done <"$PATTERNS"

if [[ $any -eq 0 ]]; then
  echo "NO_HITS"
fi
