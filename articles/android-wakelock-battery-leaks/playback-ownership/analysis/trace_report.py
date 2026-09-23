#!/usr/bin/env python3
"""Sanitized trace validation, using a locally installed Perfetto trace processor."""
import argparse
import csv
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys

spec = importlib.util.spec_from_file_location('base_report', Path(__file__).with_name('report.py'))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def query(processor, trace, sql):
    command = ([sys.executable, str(processor)] if processor.suffix == '.py' or not processor.stat().st_mode & 0o111 else [str(processor)])
    result = subprocess.run(command + ['query', str(trace), sql], capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError('Trace processor query failed; inspect private trace locally')
    return list(csv.DictReader(io.StringIO(result.stdout)))


def match_markers(events, markers, prefix):
    # Match exact current-run event, PID and sequence; never export event text or PIDs.
    index = {}
    for marker in markers:
        key = (int(marker['pid']), marker['name'])
        index.setdefault(key, []).append(int(marker['ts']))
    offsets = []
    unmatched = ambiguous = 0
    for event in events:
        if not all(isinstance(event.get(k), int) for k in ('pid', 'seq', 'elapsed_ns')):
            unmatched += 1
            continue
        key = (event['pid'], f"{prefix}:{event['seq']}:{event.get('event', '')}"[:127])
        candidates = index.get(key, [])
        if len(candidates) == 1:
            offsets.append(candidates[0] - event['elapsed_ns'])
        elif candidates:
            ambiguous += 1
        else:
            unmatched += 1
    return {'matched_events': len(offsets), 'unmatched_events': unmatched, 'ambiguous_events': ambiguous,
            'marker_minus_app_elapsed_ns_min': min(offsets) if offsets else None,
            'marker_minus_app_elapsed_ns_max': max(offsets) if offsets else None}


def generate(directory, processor):
    directory, processor = Path(directory), Path(processor)
    trace = directory / 'private/trace.pftrace'
    report = {'trace_present': trace.exists(), 'suspend_interpretation': 'not_assessed; event counts do not prove successful suspend',
              'limitations': ['Counts cover the full trace, including setup and boundary dumps.',
                             'Markers are emitted after app timestamps; offsets include logging overhead.',
                             'Clock snapshots and counts alone do not prove interval coverage or causal suspend blocking.']}
    if not trace.exists():
        report['status'] = 'trace_missing'
    else:
        try:
            manifest = json.loads((directory / 'manifest.json').read_text())
            event_file = directory / 'events.jsonl'
            events, malformed = base.read_events(event_file.read_text() if event_file.exists() else '', manifest['run_id'])
            stats = query(processor, trace, "SELECT name,severity,value FROM stats WHERE value != 0 AND (severity != 'info' OR name GLOB '*overrun*' OR name GLOB '*loss*' OR name GLOB '*drop*')")
            # Stats names are schema identifiers, but allow only ASCII identifiers to avoid arbitrary source strings.
            import re
            report['nonzero_validation_stats'] = [{'name': s['name'], 'severity': s['severity'], 'value': int(s['value'])}
                for s in stats if re.fullmatch(r'[a-zA-Z0-9_]+', s['name']) and s['severity'] in ('info', 'notice', 'data_loss', 'error')]
            clocks = query(processor, trace, "SELECT COUNT(*) AS snapshots, MAX(ABS(ts-clock_value)) AS maximum_offset_ns FROM clock_snapshot WHERE clock_name='BOOTTIME'")
            report['boottime_clock'] = {k: int(v) if v and v != '[NULL]' else None for k, v in clocks[0].items()}
            markers = query(processor, trace, "SELECT s.ts,s.name,p.pid FROM slice s JOIN thread_track t ON t.id=s.track_id JOIN thread th USING(utid) JOIN process p USING(upid) WHERE s.name GLOB 'PL:*' OR s.name GLOB 'DL:*'")
            report['app_markers'] = match_markers(events, markers, 'DL' if manifest['scenario'].startswith('direct-') else 'PL')
            report['malformed_event_line_count'] = len(malformed)
            count = query(processor, trace, "SELECT COUNT(*) AS count FROM ftrace_event WHERE name='suspend_resume'")
            report['suspend_resume_event_count'] = int(count[0]['count'])
            report['status'] = 'requires_manual_review'
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired):
            report['status'] = 'validation_failed'
    (directory / 'trace-report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--trace-processor', type=Path, required=True)
    args = parser.parse_args()
    generate(args.directory, args.trace_processor)
