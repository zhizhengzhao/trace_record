#!/usr/bin/env python3
"""validate.py — Pre-flight check for ARM v1.1 trace.jsonl

Mirrors the server-side anti-fraud rules used by Playground for Agentic
Science. Exit code 0 if valid, 2 if any blocking rule fails.

Rules implemented (trace-level, runnable without bundle):
  - no_steps               trace must not be empty
  - typed_step_type        every step has step_type in allowed set
  - tool_call_pairing      every tool_call has matching tool_result
  - cost_floor             total cost_usd ≥ 0.01
  - thought_chain_thin     ≥ 3 thoughts whose body ≥ 80 chars
  - zero_resource_signals  at least one step has cost_usd > 0 or tokens > 0
  - timestamp_monotonic    step timestamps must be non-decreasing
  - step_id_unique         step_id (if present) must be unique

Bundle-context rules NOT checked here (verified at submission time):
  - timestamp_window       (needs execution.ran_at ± wall_time_s)
  - artifact_existence     (needs bundle directory to look up artifact_path)
  - stdout_anchor          (needs execution/run.log to grep against)
"""
import argparse
import json
import sys
from pathlib import Path


ALLOWED_TYPES = {
    'thought', 'tool_call', 'tool_result',
    'artifact', 'decision', 'error', 'observation',
}


def validate(path: Path) -> dict:
    failures: list[str] = []
    warnings: list[str] = []
    steps: list[dict] = []

    with path.open('r', encoding='utf-8') as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                steps.append(json.loads(line))
            except json.JSONDecodeError as e:
                failures.append(f'json_parse: line {ln}: {e}')

    by_type: dict[str, int] = {}
    bad_type_count = 0
    for s in steps:
        t = s.get('step_type')
        by_type[t] = by_type.get(t, 0) + 1
        if t not in ALLOWED_TYPES:
            bad_type_count += 1

    call_ids: dict[str, int] = {}
    result_ids: set[str] = set()
    for s in steps:
        st = s.get('step_type')
        cid = s.get('tool_call_id')
        if st == 'tool_call' and cid:
            call_ids[cid] = call_ids.get(cid, 0) + 1
        elif st == 'tool_result' and cid:
            result_ids.add(cid)
    paired = sum(1 for c in call_ids if c in result_ids)
    unpaired = [c for c in call_ids if c not in result_ids]
    total_calls = len(call_ids)

    total_cost = round(sum(float(s.get('cost_usd', 0) or 0) for s in steps), 6)
    total_tokens = sum(
        int(s.get('tokens_in', 0) or 0) + int(s.get('tokens_out', 0) or 0)
        for s in steps
    )

    long_thoughts = sum(
        1 for s in steps
        if s.get('step_type') == 'thought' and len(str(s.get('body', ''))) >= 80
    )

    any_signal = any(
        (float(s.get('cost_usd', 0) or 0) > 0)
        or (int(s.get('tokens_in', 0) or 0) > 0)
        or (int(s.get('tokens_out', 0) or 0) > 0)
        for s in steps
    )

    timestamps = [s.get('timestamp') for s in steps if s.get('timestamp')]
    monotonic_ok = all(
        timestamps[i] <= timestamps[i + 1] for i in range(len(timestamps) - 1)
    ) if timestamps else True

    ids = [s.get('step_id') for s in steps if s.get('step_id')]
    dup_ids = len(ids) - len(set(ids))

    if not steps:
        failures.append('no_steps: trace is empty')
    if bad_type_count:
        failures.append(
            f'typed_step_type: {bad_type_count} steps with invalid step_type '
            f'(allowed: {sorted(ALLOWED_TYPES)})'
        )
    if unpaired:
        failures.append(
            f'tool_call_pairing: {len(unpaired)} tool_calls without matching '
            f'tool_result (ids: {unpaired[:5]}{"..." if len(unpaired) > 5 else ""})'
        )
    if total_cost < 0.01:
        failures.append(
            f'cost_floor: total_cost_usd={total_cost:.6f} < 0.01'
        )
    if long_thoughts < 3:
        failures.append(
            f'thought_chain_thin: {long_thoughts} thoughts ≥80 chars (need 3)'
        )
    if not any_signal and steps:
        failures.append(
            'zero_resource_signals: every step has cost=0 and tokens=0'
        )
    if not monotonic_ok:
        failures.append('timestamp_monotonic: step timestamps not non-decreasing')
    if dup_ids:
        failures.append(f'step_id_unique: {dup_ids} duplicate step_id values')

    warnings.append(
        'timestamp_window not checked here; ensure execution.ran_at + '
        'wall_time_s covers all step timestamps when packing the bundle.'
    )
    warnings.append(
        'artifact_existence not checked here; ensure every step_type=artifact '
        'row has artifact_path that exists in the bundle.'
    )
    warnings.append(
        'stdout_anchor not checked here; ensure at least one step body is '
        'greppable in execution/run.log.'
    )

    return {
        'path': str(path),
        'total_steps': len(steps),
        'by_type': by_type,
        'paired_tool_calls': f'{paired}/{total_calls}',
        'total_cost_usd': total_cost,
        'total_tokens': total_tokens,
        'failures': failures,
        'warnings': warnings,
        'valid': len(failures) == 0,
    }


def main():
    ap = argparse.ArgumentParser(
        description='Validate ARM v1.1 trace.jsonl against Playground anti-fraud rules.'
    )
    ap.add_argument('trace', help='Path to trace.jsonl')
    args = ap.parse_args()

    p = Path(args.trace).expanduser()
    if not p.exists():
        print(f'error: {p} not found', file=sys.stderr)
        sys.exit(2)

    report = validate(p)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    sys.exit(0 if report['valid'] else 2)


if __name__ == '__main__':
    main()
