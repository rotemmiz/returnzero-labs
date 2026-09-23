#!/usr/bin/env python3
"""Allowlisted numeric evidence for issue 565052666; raw inputs stay private."""
import argparse
import importlib.util
import json
import re
from pathlib import Path

_spec = importlib.util.spec_from_file_location('ownership_report', Path(__file__).with_name('report.py'))
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)


def duration_ms(value):
    tokens = re.findall(r'(\d+(?:\.\d+)?)(ms|d|h|m|s)', value)
    if not tokens or re.sub(r'\d+(?:\.\d+)?(?:ms|d|h|m|s)|\s+', '', value):
        return None
    scales = {'d': 86400000, 'h': 3600000, 'm': 60000, 's': 1000, 'ms': 1}
    return sum(float(number) * scales[unit] for number, unit in tokens)


def battery(text, uid):
    section = base.uid_section(text, uid)
    if section is None:
        return {'uid_present': False, 'audiomix_partial_ms': None, 'direct_partial_ms': None}
    result = {'uid_present': True, 'audiomix_partial_ms': None, 'direct_partial_ms': None}
    for name, key in [('AudioMix', 'audiomix_partial_ms'), ('DirectLockLab', 'direct_partial_ms')]:
        values = []
        for line in section.splitlines():
            match = re.search(r'Wake lock ' + name + r'(?:[:](?:direct-untimed|direct-timed))?:\s*(.*?)\s+partial\b', line)
            if match:
                values.append(duration_ms(match.group(1)))
        if values and all(v is not None for v in values):
            result[key] = sum(values)
    return result


def power(text, uid):
    rows = []
    for line in text.splitlines():
        if 'PARTIAL_WAKE_LOCK' not in line:
            continue
        owner = re.search(r'\buid=(\d+)\b', line)
        worksource = re.search(r'\b(?:ws|workSource)=WorkSource\{([^}]*)\}', line)
        attributed = worksource and re.search(r'(?<!\d)' + str(uid) + r'(?!\d)', worksource.group(1))
        if not (owner and int(owner.group(1)) == uid) and not attributed:
            continue
        disabled = re.search(r'\bdisabled=(true|false)\b', line, re.I)
        # Android builds use both DISABLED and disabled=true. Absence alone is unknown.
        disabled_value = disabled.group(1).lower() == 'true' if disabled else (True if re.search(r'\bDISABLED\b', line) else None)
        rows.append({'kind': 'audiomix' if re.search(r"['\"]AudioMix['\"]", line) else 'direct' if 'DirectLockLab' in line else 'other',
                     'owned_by_sample_uid': bool(owner and int(owner.group(1)) == uid),
                     'worksource_attributes_sample_uid': bool(attributed), 'disabled': disabled_value})
    return {'sample_partial_rows': rows, 'row_count': len(rows),
            'interpretation': 'snapshot_only; zero rows or unknown disabled flags do not establish suspend'}


def audio_tracks(text, uid):
    counts = []
    active_count = 0
    client_tables = 0
    incomplete_tables = 0
    remaining = 0
    client_table = False
    column = None
    recognized_tables = 0
    for line in text.splitlines():
        cells = line.split()
        table = re.match(r'^\s*(\d+) Tracks of which \d+ are active\s*$', line)
        if table:
            remaining = int(table.group(1))
            client_table = False
            continue
        if remaining and 'Client(pid/uid)' in line and 'Active' in cells and 'Type' in cells:
            client_table = True
            client_tables += 1
            recognized_tables += 1
            continue
        if client_table and remaining:
            row = re.match(r'^\s*(?:F\d+\s+)?(?:S\s+)?\d+\s+(yes|no)\s+\d+/\s*(\d+)\s+', line)
            if row:
                remaining -= 1
                if int(row.group(2)) == uid:
                    counts.append(1)
                    active_count += row.group(1) == 'yes'
                if remaining == 0:
                    client_table = False
                continue
            incomplete_tables += 1
            client_table = False
            remaining = 0
        if 'Name' in cells and ('Uid' in cells or 'UID' in cells):
            column = cells.index('Uid') if 'Uid' in cells else cells.index('UID')
            recognized_tables += 1
            continue
        if column is not None:
            if not cells:
                column = None
            elif len(cells) > column and cells[column].isdigit():
                if int(cells[column]) == uid:
                    counts.append(1)
            else:
                column = None
    incomplete_tables += int(client_table and remaining > 0)
    return {'sample_track_rows': sum(counts) if recognized_tables and not incomplete_tables else None,
            'recognized_uid_tables': recognized_tables,
            'sample_active_track_rows': active_count if client_tables and not incomplete_tables else None,
            'incomplete_tables': incomplete_tables,
            'interpretation': 'Recognized current track tables only; Active is a dump flag, not proof of audible output or suspend blocking'}


def process(text, uid):
    labels = {str(uid), f'u{uid // 100000}_a{uid % 100000 - 10000}'}
    lines = text.splitlines()
    if not lines or 'UID' not in lines[0].split():
        return {'sample_processes': None, 'process_states': None}
    header = lines[0].split()
    column = header.index('UID')
    states = []
    count = 0
    for line in lines[1:]:
        cells = line.split()
        if len(cells) > column and cells[column] in labels:
            count += 1
            if 'STAT' in header and len(cells) > header.index('STAT'):
                state = cells[header.index('STAT')]
                if re.fullmatch(r'[RSDTtZXIW<NLsl+]+', state):
                    states.append(state)
    return {'sample_processes': count, 'process_states': states if 'STAT' in header else None}


def app_summary(events, scenario):
    if scenario == 'idle':
        return {'evidence': 'not_applicable_idle', 'events': len(events)}
    if scenario.startswith('direct-'):
        names = [e.get('event') for e in events]
        return {'evidence': 'app_records_only' if events else 'inconclusive', 'events': len(events),
                'event_counts': {name: names.count(name) for name in DIRECT_EVENTS},
                'release_reasons': {reason: sum(e.get('event') == 'wake_lock_release' and e.get('reason') == reason for e in events)
                                    for reason in ('timeout_observed', 'deadline_cleanup', 'explicit_stop', 'lifecycle_destroy', 'scenario_switch')},
                'interpretation': 'acquire/release and isHeld describe app observations, not effective suspend blocking'}
    return base.summarize_events(events)


DIRECT_EVENTS = ('wake_lock_acquired', 'wake_lock_timeout_observed', 'wake_lock_release', 'run_stop', 'experiment_deadline', 'activity_stopped')


def generate(directory):
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text())
    event_file = directory / 'events.jsonl'
    events, malformed = base.read_events(event_file.read_text() if event_file.exists() else '', manifest['run_id'])
    uid = manifest.get('app_uid')
    snapshots = {}
    if isinstance(uid, int):
        readers = [('batterystats', battery), ('power', power), ('audio-flinger', audio_tracks), ('processes', process)]
        for suffix, reader in readers:
            for path in sorted((directory / 'private').glob('*-' + suffix + '.txt')):
                boundary = path.name.removesuffix('-' + suffix + '.txt')
                snapshots.setdefault(boundary, {})[suffix] = reader(path.read_text(errors='replace'), uid)
    before = snapshots.get('play-end', {}).get('batterystats', {})
    after = snapshots.get('observe-end', {}).get('batterystats', {})
    deltas = {}
    for key in ('audiomix_partial_ms', 'direct_partial_ms'):
        start, end = before.get(key), after.get(key)
        deltas[key] = end - start if start is not None and end is not None and end >= start else None
    observation_file = directory / 'events-before-cleanup.jsonl'
    observation_events, observation_malformed = base.read_events(observation_file.read_text() if observation_file.exists() else '', manifest['run_id'])
    failed = manifest.get('status') != 'completed' or bool(malformed) or bool(observation_malformed)
    report = {'run_id': manifest['run_id'], 'scenario': manifest['scenario'], 'capture_status': manifest.get('status'),
              'classification': 'inconclusive', 'capture_validity': 'incomplete_or_corrupt' if failed else 'requires_manual_evidence_review',
              'app': app_summary(events, manifest['scenario']),
              'app_before_cleanup': app_summary(observation_events, manifest['scenario']),
              'before_cleanup_events_available': observation_file.exists(),
              'malformed_before_cleanup_event_lines': observation_malformed, 'malformed_event_lines': malformed,
              'snapshots': snapshots, 'batterystats_delta': {'from': 'play-end', 'to': 'observe-end', **deltas},
              'limitations': ['Deltas include sequential dump and screen-off transition overhead, not only the quiet interval.',
                             'Absent UID, timer, or track rows are unknown, never inferred zero.',
                             'BatteryStats timers are attributed accounting, not measured prevented suspend.',
                             'Power rows are instantaneous; disabled state remains unknown unless explicit.',
                             'Perfetto availability, clock alignment and data-loss statistics require separate review.',
                             'No automated suspension, causality, battery-life or indefinite-duration conclusion.']}
    (directory / 'issue-report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    generate(parser.parse_args().directory)
