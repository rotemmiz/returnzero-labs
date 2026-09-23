#!/usr/bin/env python3
"""Sanitized trace validation, using a locally installed Perfetto trace processor."""
import argparse
import csv
import importlib.util
import io
import json
import re
from decimal import Decimal
from pathlib import Path
import subprocess
import sys

spec = importlib.util.spec_from_file_location('base_report', Path(__file__).with_name('report.py'))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def processor_command(processor):
    return [sys.executable, str(processor)] if processor.suffix == '.py' or not processor.stat().st_mode & 0o111 else [str(processor)]


def processor_version(processor):
    result = subprocess.run(processor_command(processor) + ['--version'], capture_output=True, text=True, timeout=30)
    if result.returncode:
        return None
    for line in result.stdout.splitlines():
        if re.fullmatch(r'Perfetto v[0-9]+\.[0-9]+(?:-[a-f0-9]+)?(?: \([a-f0-9]{40}\))?', line):
            return line
    return None


def validated_version(version):
    return bool(version and re.match(r'^Perfetto v58\.2(?:-| |$)', version))


def query(processor, trace, sql):
    result = subprocess.run(processor_command(processor) + ['query', str(trace), sql], capture_output=True, text=True, timeout=120)
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


def quiet_alignment(manifest, directory):
    """Intersect ADB-bracketed BOOTTIME offsets; /proc/uptime is truncated to 10ms."""
    boundaries = manifest.get('boundaries', [])
    quiet = {b['boundary']: b['host_monotonic_ns'] for b in boundaries
             if b['boundary'] in ('quiet-screen-off-start', 'quiet-screen-off-end')}
    start, end = quiet.get('quiet-screen-off-start'), quiet.get('quiet-screen-off-end')
    if start is None or end is None or end <= start:
        return None
    offsets, sample_times = [], []
    used = set()
    for cmd in manifest.get('commands', []):
        if cmd.get('returncode') != 0 or cmd.get('command') != ['shell', 'sh', '-c', 'date +%s; cat /proc/uptime']:
            continue
        host_start, host_end = cmd['start_host_ns'], cmd['end_host_ns']
        candidates = [b for b in boundaries if b['host_monotonic_ns'] <= host_start
                      and (Path(directory) / 'private' / (b['boundary'] + '-clock.txt')).exists()]
        if not candidates or host_end < host_start:
            return None
        boundary = max(candidates, key=lambda b: b['host_monotonic_ns'])['boundary']
        if boundary in used:
            return None
        used.add(boundary)
        text = (Path(directory) / 'private' / (boundary + '-clock.txt')).read_text()
        matches = re.findall(r'^(\d+\.\d{2}) \d+\.\d{2}\s*$', text, re.M)
        if len(matches) != 1:
            return None
        boot = int(Decimal(matches[0]) * 1000000000)
        offsets.append((boot - host_end, boot + 10000000 - host_start))
        sample_times.append((host_start, host_end))
    if len(offsets) < 2 or not any(b <= start for a, b in sample_times) or not any(a >= end for a, b in sample_times):
        return None
    low, high = max(a for a, b in offsets), min(b for a, b in offsets)
    if low > high:
        return None
    return {'offset_lower_ns': low, 'offset_upper_ns': high, 'clock_samples': len(offsets),
            'outer_start_ns': start + low, 'inner_start_ns': start + high,
            'inner_end_ns': end + low, 'outer_end_ns': end + high,
            'quiet_host_duration_ns': end - start}


def overlap_duration(intervals, start, end):
    if start >= end:
        return 0
    merged = []
    for a, b in sorted((max(a, start), min(b, end)) for a, b in intervals if a < end and b > start):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return sum(b - a for a, b in merged)


def suspend_evidence(manifest, directory, clocks, stats, intervals, sources, bounds):
    result = {'status': 'unavailable', 'reference_method': 'Perfetto v58.2 android.suspend',
              'source': 'https://github.com/google/perfetto/blob/v58.2/src/trace_processor/perfetto_sql/stdlib/android/suspend.sql',
              'interpretation': 'Detected suspend intervals only; no causal wake-lock or battery-life conclusion.',
              'caveats': ['The module prefers minimal suspend slices and otherwise uses syscore_resume/timekeeping_freeze latency slices.',
                          'The module labels gaps awake, including when no source slices exist; that fallback is not evidence of absence.',
                          'Alignment assumes a constant host-monotonic to device-BOOTTIME offset during the trial; inconsistent samples are rejected.',
                          'Reported bounds include clock-read brackets and 10ms uptime quantization, but cannot exclude unreported event loss or clock drift within the sample brackets.']}
    alignment = quiet_alignment(manifest, directory)
    if not alignment:
        result['reason'] = 'missing_or_inconsistent_clock_alignment'
    elif clocks.get('snapshots', 0) < 1 or clocks.get('maximum_offset_ns') != 0:
        result['reason'] = 'trace_boottime_alignment_unverified'
    elif any(s['severity'] in ('data_loss', 'error') or any(k in s['name'] for k in ('overrun', 'loss', 'drop')) for s in stats):
        result['reason'] = 'reported_trace_loss_or_error'
    elif sources < 1:
        result['reason'] = 'no_supported_suspend_source_slices'
    elif not intervals:
        result['reason'] = 'no_usable_suspend_intervals'
    elif int(bounds[0]['start_ts']) > alignment['outer_start_ns'] or int(bounds[0]['end_ts']) < alignment['outer_end_ns']:
        result['reason'] = 'quiet_window_not_fully_covered_by_trace'
    else:
        result.update(status='detected_interval_bounds', alignment=alignment,
                      suspend_source_slices=sources,
                      suspended_ns_lower=overlap_duration(intervals, alignment['inner_start_ns'], alignment['inner_end_ns']),
                      suspended_ns_upper=overlap_duration(intervals, alignment['outer_start_ns'], alignment['outer_end_ns']))
    return result


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
            report['trace_processor_version'] = processor_version(processor)
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
            try:
                if not validated_version(report['trace_processor_version']):
                    raise ValueError('Unvalidated suspend module runtime')
                intervals = query(processor, trace, "INCLUDE PERFETTO MODULE android.suspend; SELECT ts,dur FROM android_suspend_state WHERE power_state='suspended' AND machine_id=0 AND dur>=0")
                sources = query(processor, trace, "SELECT COUNT(*) AS count FROM slice s JOIN track t ON s.track_id=t.id WHERE COALESCE(t.machine_id,0)=0 AND s.dur>=0 AND (t.name='Suspend/Resume Minimal' OR (t.name='Suspend/Resume Latency' AND s.name IN ('syscore_resume(0)','timekeeping_freeze(0)')))")
                bounds = query(processor, trace, "SELECT start_ts,end_ts FROM trace_bounds")
                report['quiet_suspend'] = suspend_evidence(manifest, directory, report['boottime_clock'], report['nonzero_validation_stats'],
                    [(int(row['ts']), int(row['ts']) + int(row['dur'])) for row in intervals], int(sources[0]['count']), bounds)
            except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired):
                report['quiet_suspend'] = {'status': 'unavailable', 'reason': 'suspend_module_query_failed' if validated_version(report['trace_processor_version']) else 'suspend_module_runtime_not_validated'}
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
