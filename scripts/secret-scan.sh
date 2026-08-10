#!/usr/bin/env bash

set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-all}"
fail=0
files=()

if [[ "$MODE" == "--staged" ]]; then
    git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null
    while IFS= read -r -d '' path; do
        files+=("$ROOT/$path")
    done < <(git -C "$ROOT" diff --cached --name-only --diff-filter=ACMR -z)
else
    while IFS= read -r -d '' path; do
        files+=("$path")
    done < <(find "$ROOT" -path "$ROOT/.git" -prune -o -type f -print0)
fi

for path in "${files[@]}"; do
    rel="${path#"$ROOT/"}"
    case "$rel" in
        .ssh/*|.gnupg/*|*/.ssh/*|*/.gnupg/*|*keyrings/*|*browser*profile*|*cookies*|*credentials*|*secrets*)
            printf 'FORBIDDEN PATH: %s\n' "$rel" >&2
            fail=1
            ;;
    esac
    size="$(stat -c %s "$path")"
    if (( size > 100000000 )); then
        printf 'FILE OVER 100 MB: %s (%s bytes)\n' "$rel" "$size" >&2
        fail=1
    fi
done

high_confidence='(-----BEGIN ([A-Z0-9 ]+ )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{16,}|[0-9]{8,10}:[A-Za-z0-9_-]{35}|Authorization:[[:space:]]*Bearer[[:space:]]+[A-Za-z0-9._~+/-]{16,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})'

for path in "${files[@]}"; do
    rel="${path#"$ROOT/"}"
    if grep -Iq . "$path"; then
        if rg -n --pcre2 "$high_confidence" "$path"; then
            printf 'HIGH-CONFIDENCE SECRET: %s\n' "$rel" >&2
            fail=1
        fi
    else
        if strings -n 12 "$path" | rg -n --pcre2 "$high_confidence"; then
            printf 'HIGH-CONFIDENCE SECRET IN BINARY: %s\n' "$rel" >&2
            fail=1
        fi
    fi
done

printf '\nKeyword review (context only; placeholders and UI labels are expected):\n'
for path in "${files[@]}"; do
    grep -Iq . "$path" || continue
    rg -n -i '(password|passwd|token|secret|api[_-]?key|apikey|authorization|cookie|session|client[_-]?secret|private[_-]?key)' "$path" || true
done

if (( fail != 0 )); then
    printf '\nSecret scan FAILED. Do not commit or push.\n' >&2
    exit 1
fi
printf '\nSecret scan passed: %s files checked.\n' "${#files[@]}"
