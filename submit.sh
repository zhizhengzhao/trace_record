#!/usr/bin/env bash
# submit.sh — convert BohrClaw trajectory.jsonl → ARM v1.1 trace.jsonl
#             and copy the raw trajectory for inclusion in your bundle.
#
# Scope: trace_record only does two things.
#   (1) Format conversion: trajectory.jsonl → ARM v1.1 trace.jsonl
#   (2) Raw data collection: copy trajectory.jsonl → raw_trajectory.jsonl
# Bundle assembly + Playground upload are the agent's responsibility.
#
# Usage:
#   trace-submit                          # auto-pick most recent trajectory
#   trace-submit --session <SID>          # explicit session id (multi-chat safe)
#   trace-submit -s <SID>                 # short form
#   trace-submit --list                   # list recent trajectories
#   trace-submit --help                   # this help
#
# Or without install.sh:
#   bash <(curl -sL https://raw.githubusercontent.com/zhizhengzhao/trace_record/main/submit.sh) [flags]
#
# Output (in current directory):
#   ./trace/<session_id>/trace.jsonl            ← ARM v1.1 trace
#   ./trace/<session_id>/raw_trajectory.jsonl   ← original BohrClaw trajectory
#   ./trace/latest -> <session_id>/             ← convenience symlink
#
# Env overrides:
#   TRACE_RECORD_PREFIX     tool install dir       (default: /opt/trace_record)
#   OPENCLAW_SESSION_DIR    sessions dir           (default: /root/.openclaw/agents/main/sessions)
#   OPENCLAW_SESSION_ID     fallback session id    (no default)
#   TRACE_OUT_DIR           output dir             (default: $PWD/trace/<sid>)
#
# Exit: 0 = trace valid, 2 = invalid or failure.

set -uo pipefail

OWNER="zhizhengzhao"
REPO="trace_record"
BRANCH="main"
PREFIX="${TRACE_RECORD_PREFIX:-/opt/trace_record}"
SESSION_DIR="${OPENCLAW_SESSION_DIR:-/root/.openclaw/agents/main/sessions}"

ACTION=""
SESSION_ID="${OPENCLAW_SESSION_ID:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --session|-s) SESSION_ID="${2:-}"; shift 2 ;;
    --list|-l)    ACTION="list"; shift ;;
    -h|--help)    ACTION="help"; shift ;;
    *) echo "[submit] unknown arg: $1" >&2; ACTION="help"; shift ;;
  esac
done

if [ "$ACTION" = "help" ]; then
  sed -n '2,32p' "$0" | sed 's|^# \?||'
  exit 0
fi

raw() { echo "https://raw.githubusercontent.com/$OWNER/$REPO/$BRANCH/$1"; }
ensure() {
  local name=$1
  [ -f "$PREFIX/$name" ] && return 0
  echo "[submit] tools not pre-installed, downloading $name on demand ..."
  mkdir -p "$PREFIX" 2>/dev/null || PREFIX=/tmp/trace_record_runtime && mkdir -p "$PREFIX"
  curl -fsSL "$(raw "$name")" -o "$PREFIX/$name" || {
    echo "[submit] ERROR: failed to download $name" >&2; exit 2;
  }
}
ensure arkclaw_to_arm.py
ensure validate.py

# ── list mode ──
if [ "$ACTION" = "list" ]; then
  echo "[submit] recent trajectories in $SESSION_DIR:"
  for f in $(ls -t "$SESSION_DIR"/*.trajectory.jsonl 2>/dev/null | head -10); do
    sid=$(basename "$f" .trajectory.jsonl)
    mtime=$(stat -c '%y' "$f" 2>/dev/null | cut -d. -f1)
    lines=$(wc -l < "$f")
    last_prompt=$(python3 - <<PY
import json
last = ""
try:
    for line in open("$f"):
        d = json.loads(line)
        if d.get("type") == "prompt.submitted":
            last = (d.get("data") or {}).get("prompt", "")[:90].replace("\n", " ")
except Exception: pass
print(last)
PY
)
    printf "  %s  (%d lines, %s)\n" "$sid" "$lines" "$mtime"
    [ -n "$last_prompt" ] && printf "      last prompt: %s\n" "$last_prompt"
  done
  exit 0
fi

# ── pick trajectory ──
if [ -n "$SESSION_ID" ]; then
  TRAJ="$SESSION_DIR/$SESSION_ID.trajectory.jsonl"
  if [ ! -f "$TRAJ" ]; then
    echo "[submit] ERROR: session $SESSION_ID not found at $TRAJ" >&2
    echo "         use: trace-submit --list  to see available sessions" >&2
    exit 2
  fi
  echo "[submit] using explicit session: $SESSION_ID"
else
  TRAJ=$(ls -t "$SESSION_DIR"/*.trajectory.jsonl 2>/dev/null | head -1)
  if [ -z "$TRAJ" ]; then
    echo "[submit] ERROR: no *.trajectory.jsonl in $SESSION_DIR" >&2
    echo "         set OPENCLAW_SESSION_DIR if your install uses a different path." >&2
    exit 2
  fi
  recent_count=$(find "$SESSION_DIR" -name "*.trajectory.jsonl" -mmin -5 2>/dev/null | wc -l | tr -d ' ')
  if [ "${recent_count:-0}" -gt 1 ]; then
    echo "[submit] ⚠️  WARNING: $recent_count trajectories active in last 5 min."
    echo "[submit]    Auto-picked most recent: $(basename "$TRAJ")"
    echo "[submit]    If wrong session, rerun with: trace-submit --session <correct-session-id>"
    echo "[submit]    See all:                       trace-submit --list"
    echo
  fi
fi

SID=$(basename "$TRAJ" .trajectory.jsonl)
echo "[submit] trajectory:  $TRAJ"
echo "[submit] session id:  $SID  ($(wc -l < "$TRAJ") lines)"

# ── output paths (session-scoped to prevent clobber) ──
OUT_DIR="${TRACE_OUT_DIR:-$PWD/trace/$SID}"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/trace.jsonl"
RAW_OUT="$OUT_DIR/raw_trajectory.jsonl"

# ── convert + copy raw ──
echo "[submit] converting → $OUT"
python3 "$PREFIX/arkclaw_to_arm.py" --in "$TRAJ" --out "$OUT" --raw-out "$RAW_OUT"

echo "[submit] validating"
python3 "$PREFIX/validate.py" "$OUT"
RC=$?

# convenience symlink (only when default TRACE_OUT_DIR layout is used)
if [ -z "${TRACE_OUT_DIR:-}" ]; then
  ln -sfn "$SID" "$PWD/trace/latest" 2>/dev/null || true
fi

if [ $RC -eq 0 ]; then
  echo
  echo "[submit] ✓ valid."
  echo "[submit]   ARM trace:        $OUT"
  echo "[submit]   raw trajectory:   $RAW_OUT"
  echo "[submit]"
  echo "[submit] next: put these into your ARM bundle:"
  echo "[submit]   ARM/trace/trace.jsonl       ← cp $OUT"
  echo "[submit]   ARM/raw_messages.jsonl      ← cp $RAW_OUT"
  echo "[submit] then add your src/, results/, execution/, characterization.json, manifest, README,"
  echo "[submit] zip the bundle, and POST it per Playground docs."
else
  echo
  echo "[submit] ✗ trace validation failed (exit $RC). See failures above." >&2
fi
exit $RC
