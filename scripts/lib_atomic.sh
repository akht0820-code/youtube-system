#!/usr/bin/env bash
# 原子的ファイル書き込みヘルパ（シェル版）
# 設計方針: .tmp → mv 必須、Python版 _atomic.py と同契約

set -u

# atomic_write_text <path> <data>
atomic_write_text() {
    local path="$1"
    local data="$2"
    local dir
    dir="$(dirname -- "$path")"
    mkdir -p -- "$dir"
    local tmp
    tmp="$(mktemp "${dir}/.$(basename -- "$path").XXXXXX.tmp")" || return 1
    printf '%s' "$data" > "$tmp" || { rm -f -- "$tmp"; return 1; }
    mv -f -- "$tmp" "$path" || { rm -f -- "$tmp"; return 1; }
}

# atomic_write_json <path> <json_string>
# 注意: JSONのバリデーションは呼び出し側の責務
atomic_write_json() {
    atomic_write_text "$1" "$2"
}

# atomic_update_field_json <path> <field> <value>
# 既存JSONの1フィールドを更新 (python3 依存)
atomic_update_field_json() {
    local path="$1"
    local field="$2"
    local value="$3"
    local new_content
    new_content="$(python3 -c "
import json,sys
try:
    with open('$path', encoding='utf-8') as f:
        d = json.load(f)
except Exception:
    d = {}
d['$field'] = $value
print(json.dumps(d, ensure_ascii=False))
" 2>/dev/null)" || return 1
    atomic_write_text "$path" "$new_content"
}
