#!/usr/bin/env bash
# install.sh — one-line install for BohrClaw / arkclaw contestants.
#
# Usage (from any cwd):
#   curl -sL https://raw.githubusercontent.com/zhizhengzhao/trace_record/main/install.sh | bash
#
# What it does:
#   1. Downloads arkclaw_to_arm.py + validate.py + submit.sh to PREFIX
#   2. Symlinks PREFIX/submit.sh → ~/.local/bin/trace-submit
#   3. Verifies tools can run --help
#
# Re-running is safe (idempotent). Overwrites tool files but not state.

set -uo pipefail

OWNER="zhizhengzhao"
REPO="trace_record"
BRANCH="main"
PREFIX="${TRACE_RECORD_PREFIX:-/opt/trace_record}"
BIN_DIR="${TRACE_RECORD_BIN:-$HOME/.local/bin}"
CMD_NAME="trace-submit"

if [ -t 1 ]; then
  GREEN=$'\033[0;32m'; YEL=$'\033[0;33m'; RED=$'\033[0;31m'; DIM=$'\033[0;90m'; NC=$'\033[0m'
else
  GREEN=''; YEL=''; RED=''; DIM=''; NC=''
fi
say()  { printf "${GREEN}[install]${NC} %s\n" "$*"; }
warn() { printf "${YEL}[install]${NC} %s\n" "$*"; }
die()  { printf "${RED}[install] ERROR:${NC} %s\n" "$*" >&2; exit 1; }
dim()  { printf "${DIM}  %s${NC}\n" "$*"; }

say "trace_record installer"
dim "PREFIX  = $PREFIX"
dim "BIN_DIR = $BIN_DIR"

command -v python3 >/dev/null 2>&1 || die "python3 not found (need Python 3.8+)"
command -v curl    >/dev/null 2>&1 || die "curl not found"

say "creating directories"
mkdir -p "$PREFIX" "$BIN_DIR" || die "cannot create $PREFIX or $BIN_DIR"

raw() { echo "https://raw.githubusercontent.com/$OWNER/$REPO/$BRANCH/$1"; }

for f in arkclaw_to_arm.py validate.py submit.sh; do
  say "downloading $f"
  curl -fsSL "$(raw "$f")" -o "$PREFIX/$f" || die "failed to download $f"
done
chmod +x "$PREFIX/submit.sh"

say "linking $CMD_NAME → $BIN_DIR/"
ln -sf "$PREFIX/submit.sh" "$BIN_DIR/$CMD_NAME"

say "self-test"
python3 "$PREFIX/arkclaw_to_arm.py" --help >/dev/null 2>&1 \
  && dim "arkclaw_to_arm.py --help: OK" \
  || die "arkclaw_to_arm.py self-test failed"
python3 "$PREFIX/validate.py"       --help >/dev/null 2>&1 \
  && dim "validate.py --help: OK" \
  || die "validate.py self-test failed"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) warn "$BIN_DIR is not in PATH; add this to your shell rc:"
     warn "    export PATH=\"$BIN_DIR:\$PATH\""
     warn "Or run trace-submit by full path: $PREFIX/submit.sh" ;;
esac

echo
say "installed."
echo
echo "Next steps:"
echo "  1. Do your work in BohrClaw chat as usual."
echo "  2. When done, run:"
echo "       ${GREEN}trace-submit --session <your-session-id>${NC}"
echo "     (or just ${GREEN}trace-submit${NC} if you have only one active chat)"
echo "  3. The output (trace.jsonl + raw_trajectory.jsonl) goes into ./trace/<sid>/."
echo "     Add them to your ARM bundle, then upload per Playground docs."
echo
echo "  Tip: ${DIM}trace-submit --list${NC} shows recent trajectories with last prompt."
echo
