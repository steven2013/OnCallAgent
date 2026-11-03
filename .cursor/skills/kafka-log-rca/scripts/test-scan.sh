#!/usr/bin/env bash
# Checks scanner hits against fixtures/expect.tsv.
set -euo pipefail

BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCAN="${BASE}/scripts/scan-kafka-logs.sh"
EXPECT="${BASE}/fixtures/expect.tsv"
fail=0

while IFS=$'\t' read -r file required forbidden; do
  [[ -z "${file:-}" || "$file" == \#* ]] && continue
  out="$("$SCAN" "${BASE}/fixtures/${file}")"
  ids="$(printf '%s\n' "$out" | awk -F '\t' 'NR > 1 && $1 != "NO_HITS" { print $1 }')"

  if [[ "$required" == "NONE" ]]; then
    if [[ -n "$ids" ]] || ! printf '%s\n' "$out" | grep -q '^NO_HITS$'; then
      echo "FAIL ${file}: expected no hits" >&2
      printf '%s\n' "$out" >&2
      fail=1
    fi
    continue
  fi

  IFS=',' read -ra need <<<"$required"
  for id in "${need[@]}"; do
    if ! printf '%s\n' "$ids" | grep -qx "$id"; then
      echo "FAIL ${file}: missing ${id}" >&2
      printf '%s\n' "$out" >&2
      fail=1
    fi
  done

  if [[ -n "${forbidden:-}" && "$forbidden" != "-" ]]; then
    IFS=',' read -ra ban <<<"$forbidden"
    for id in "${ban[@]}"; do
      if printf '%s\n' "$ids" | grep -qx "$id"; then
        echo "FAIL ${file}: unexpected ${id}" >&2
        printf '%s\n' "$out" >&2
        fail=1
      fi
    done
  fi
done <"$EXPECT"

if [[ $fail -ne 0 ]]; then
  exit 1
fi
echo "ok"
