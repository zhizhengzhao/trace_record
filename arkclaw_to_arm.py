#!/usr/bin/env python3
"""arkclaw_to_arm.py — OpenClaw trajectory.jsonl → ARM v1.1 trace.jsonl

读 ~/.openclaw/agents/<agentId>/sessions/<sid>.trajectory.jsonl，
输出符合 Playground for Agentic Science 反作弊检查的 trace.jsonl。

支持的 trajectory event 类型:
  session.started / trace.metadata / context.compiled /
  prompt.submitted / model.completed / trace.artifacts / session.ended

ARM step 映射:
  prompt.submitted  -> observation  (user prompt)
  model.completed   -> thought (from assistantTexts) + tool_call/tool_result
                       (from messagesSnapshot) + error (if aborted/timedOut)
  session.ended.status != success -> error

Usage:
  python3 arkclaw_to_arm.py --in <trajectory.jsonl> --out trace/trace.jsonl
"""
import argparse
import json
import re
import sys
import uuid
from pathlib import Path


# Token patterns to scrub from raw_trajectory.jsonl before it leaves the
# contestant's machine. The raw trajectory gets uploaded to Playground in
# the bundle and may later be shared as a research dataset, so any auth
# credentials accidentally pasted into chat must be redacted.
TOKEN_PATTERNS = [
    # Playground API token: asp_ + 40+ alphanumeric chars
    re.compile(r'asp_[a-zA-Z0-9]{40,}'),
    # Bearer headers that wrap any token
    re.compile(r'(Bearer\s+)[A-Za-z0-9._\-]{20,}', re.IGNORECASE),
]


def redact_tokens(text: str) -> tuple[str, int]:
    """Replace any auth tokens with <REDACTED>. Returns (clean_text, count)."""
    total = 0
    for pat in TOKEN_PATTERNS:
        text, n = pat.subn(lambda m: (
            m.group(1) + '<REDACTED>' if m.lastindex else '<asp_TOKEN_REDACTED>'
        ), text)
        total += n
    return text, total


# Approximate USD pricing (per 1M tokens). Adjust as providers update rates.
PRICE_IN = {
    "deepseek-v4-pro": 0.27,
    "deepseek-v3": 0.14,
    "claude-opus-4-7": 15.0,
    "claude-sonnet-4-6": 3.0,
    "claude-opus-4-5": 15.0,
    "claude-sonnet-4-5": 3.0,
    "gpt-4o": 2.5,
    "gpt-4o-mini": 0.15,
    "gpt-5": 5.0,
}
PRICE_OUT = {
    "deepseek-v4-pro": 1.10,
    "deepseek-v3": 0.28,
    "claude-opus-4-7": 75.0,
    "claude-sonnet-4-6": 15.0,
    "claude-opus-4-5": 75.0,
    "claude-sonnet-4-5": 15.0,
    "gpt-4o": 10.0,
    "gpt-4o-mini": 0.60,
    "gpt-5": 15.0,
}
DEFAULT_IN = 0.50
DEFAULT_OUT = 1.50


def cost(model: str, tin: int, tout: int) -> float:
    pin = PRICE_IN.get(model, DEFAULT_IN)
    pout = PRICE_OUT.get(model, DEFAULT_OUT)
    return round((tin * pin + tout * pout) / 1_000_000, 6)


def sid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def extract_tool_calls(messages, default_ts):
    """Best-effort extraction of tool_use/tool_result blocks from a snapshot."""
    out = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        content = msg.get('content')
        if not isinstance(content, list):
            continue
        msg_ts = msg.get('timestamp') or default_ts
        for block in content:
            if not isinstance(block, dict):
                continue
            t = block.get('type', '')
            if t == 'tool_use':
                out.append({
                    'step_type': 'tool_call',
                    'step_id': sid('tc'),
                    'tool_call_id': block.get('id', sid('tcid')),
                    'tool_name': block.get('name', 'unknown'),
                    'tool_args': block.get('input', {}),
                    'timestamp': msg_ts,
                })
            elif t == 'tool_result':
                txt = block.get('content', '')
                if isinstance(txt, list):
                    txt = '\n'.join(
                        c.get('text', '') for c in txt if isinstance(c, dict)
                    )
                out.append({
                    'step_type': 'tool_result',
                    'step_id': sid('tr'),
                    'tool_call_id': block.get('tool_use_id', ''),
                    'tool_output': str(txt)[:8000],
                    'timestamp': msg_ts,
                })
    return out


def convert(traj_path: Path):
    steps = []
    model_id = None

    with traj_path.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            rtype = rec.get('type', '')
            ts = rec.get('ts')
            data = rec.get('data') or {}
            model_id = model_id or rec.get('modelId')

            if rtype == 'prompt.submitted':
                p = (data.get('prompt') or '').strip()
                if p:
                    steps.append({
                        'step_type': 'observation',
                        'step_id': sid('obs'),
                        'timestamp': ts,
                        'body': f'[user prompt] {p[:8000]}',
                    })

            elif rtype == 'model.completed':
                usage = data.get('usage') or {}
                tin = int(usage.get('input', 0) or 0)
                tout = int(usage.get('output', 0) or 0)
                texts = data.get('assistantTexts') or []
                first = True
                for text in texts:
                    text = (text or '').strip()
                    if not text:
                        continue
                    step = {
                        'step_type': 'thought',
                        'step_id': sid('thought'),
                        'timestamp': ts,
                        'body': text[:8000],
                    }
                    if model_id:
                        step['model_id'] = model_id
                    if first and (tin or tout):
                        step['tokens_in'] = tin
                        step['tokens_out'] = tout
                        step['cost_usd'] = cost(model_id or '', tin, tout)
                        first = False
                    steps.append(step)

                if not texts and (tin or tout):
                    steps.append({
                        'step_type': 'thought',
                        'step_id': sid('thought'),
                        'timestamp': ts,
                        'body': '(no assistant text)',
                        'model_id': model_id,
                        'tokens_in': tin,
                        'tokens_out': tout,
                        'cost_usd': cost(model_id or '', tin, tout),
                    })

                steps.extend(extract_tool_calls(data.get('messagesSnapshot'), ts))

                if data.get('aborted') or data.get('timedOut') or data.get('idleTimedOut'):
                    steps.append({
                        'step_type': 'error',
                        'step_id': sid('err'),
                        'timestamp': ts,
                        'body': (
                            f"model run failed: aborted={data.get('aborted')} "
                            f"timedOut={data.get('timedOut')} "
                            f"idleTimedOut={data.get('idleTimedOut')}"
                        ),
                    })

            elif rtype == 'session.ended':
                st = data.get('status', '?')
                if st != 'success':
                    steps.append({
                        'step_type': 'error',
                        'step_id': sid('err'),
                        'timestamp': ts,
                        'body': f'session ended with status={st}',
                    })

    return steps


def main():
    ap = argparse.ArgumentParser(
        description='OpenClaw trajectory.jsonl -> ARM v1.1 trace.jsonl'
    )
    ap.add_argument('--in', dest='inp', required=True,
                    help='Path to <session>.trajectory.jsonl')
    ap.add_argument('--out', dest='out', required=True,
                    help='Output trace.jsonl path')
    ap.add_argument('--raw-out', dest='raw_out', default=None,
                    help='Also copy the raw trajectory.jsonl to this path '
                         '(for bundle packaging as raw_messages.jsonl). '
                         'No-op if not provided.')
    args = ap.parse_args()

    inp = Path(args.inp).expanduser()
    out = Path(args.out).expanduser()
    if not inp.exists():
        print(f'error: input not found: {inp}', file=sys.stderr)
        sys.exit(1)
    out.parent.mkdir(parents=True, exist_ok=True)

    steps = convert(inp)

    with out.open('w', encoding='utf-8') as f:
        for s in steps:
            f.write(json.dumps(s, ensure_ascii=False) + '\n')

    if args.raw_out:
        raw_out = Path(args.raw_out).expanduser()
        raw_out.parent.mkdir(parents=True, exist_ok=True)
        raw_text = inp.read_text(encoding='utf-8', errors='replace')
        clean_text, n_redacted = redact_tokens(raw_text)
        raw_out.write_text(clean_text, encoding='utf-8')
        msg = f'raw trajectory -> {raw_out} ({raw_out.stat().st_size} bytes)'
        if n_redacted:
            msg += f' [redacted {n_redacted} token(s) for safety]'
        print(msg)

    by = {}
    for s in steps:
        by[s['step_type']] = by.get(s['step_type'], 0) + 1
    tcost = sum(s.get('cost_usd', 0) for s in steps)
    ttok = sum(s.get('tokens_in', 0) + s.get('tokens_out', 0) for s in steps)

    print(f'wrote {len(steps)} steps -> {out}')
    print(f'by_type: {by}')
    print(f'cost_usd: {tcost:.6f}, tokens: {ttok}')


if __name__ == '__main__':
    main()
