#!/usr/bin/env python3
"""Conservative, standard-library-only summaries of private capture artifacts."""
import argparse
import json
import re
from collections import Counter
from pathlib import Path


def read_events(text, run_id):
    events, errors = [], []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError('expected JSON object')
            if event.get('run_id') == run_id:
                events.append(event)
        except (ValueError, TypeError):
            errors.append(number)
    return events, errors


def summarize_events(events):
    created, released = Counter(), Counter()
    issues = []
    previous = None
    for event in events:
        seq = event.get('seq')
        if isinstance(seq, int):
            if previous is not None and seq <= previous:
                issues.append('Event sequence is not strictly increasing; inspect process restarts.')
            previous = seq
        key = (event.get('pid'), event.get('player_id'))
        name = event.get('event', '')
        if key[1] is not None:
            if name in ('player_created', 'create', 'created', 'player_create'):
                created[key] += 1
            if name in ('release_end', 'released', 'player_released'):
                released[key] += 1
    missing = sum(max(count - released[key], 0) for key, count in created.items())
    duplicate = sum(max(count - created[key], 0) for key, count in released.items())
    if missing:
        issues.append(f'{missing} created player(s) lack a matching release completion in app records.')
    if duplicate:
        issues.append(f'{duplicate} unmatched/duplicate release completion(s).')
    elapsed = [e['elapsed_ns'] for e in events if isinstance(e.get('elapsed_ns'), int)]
    return {
        'events': len(events), 'players_created': sum(created.values()),
        'release_completions': sum(released.values()), 'unreleased_players': missing,
        'unmatched_releases': duplicate, 'issues': list(dict.fromkeys(issues)),
        'app_owner_evidence': 'inconclusive' if not created or issues else 'balanced_create_release_records',
        'event_span_seconds': (max(elapsed) - min(elapsed)) / 1e9 if elapsed else None,
    }


def uid_section(text, uid):
    user, app = divmod(uid, 100000)
    labels = {str(uid), f'u{user}a{app - 10000}'}
    lines = text.splitlines()
    start = None
    indent = 0
    for i, line in enumerate(lines):
        match = re.match(r'^(\s*)([\w]+):\s*$', line)
        if match and match.group(2) in labels:
            start, indent = i + 1, len(match.group(1))
            break
    if start is None:
        return None
    selected = []
    for line in lines[start:]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        selected.append(line)
    return '\n'.join(selected)


def audiomix_summary(text, uid):
    section = uid_section(text, uid)
    if section is None:
        return {'sample_uid_present': False, 'audiomix_entries': [], 'interpretation': 'unresolved'}
    entries = []
    for line in section.splitlines():
        if re.search(r'\bWake lock AudioMix:', line):
            duration = re.search(r'AudioMix:\s*(.*?)\s+partial', line)
            # Only numeric time tokens leave the private artifact directory.
            if duration and re.fullmatch(r'[\d\s.dhms]+', duration.group(1)):
                entries.append({'partial_duration_text': duration.group(1).strip()})
    return {'sample_uid_present': True, 'audiomix_entries': entries,
            'interpretation': 'cumulative_attribution_only; not measured prevented_suspend'}


def generate(directory):
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text())
    event_path = directory / 'events.jsonl'
    events, malformed = read_events(event_path.read_text() if event_path.exists() else '', manifest['run_id'])
    uid = manifest.get('app_uid')
    snapshots = {}
    if isinstance(uid, int):
        for path in sorted((directory / 'private').glob('*-batterystats.txt')):
            snapshots[path.stem.removesuffix('-batterystats')] = audiomix_summary(path.read_text(), uid)
    app_events = summarize_events(events)
    if manifest['scenario'] == 'idle' or manifest['scenario'].startswith('direct-'):
        app_events['app_owner_evidence'] = 'not_applicable_no_players_in_this_scenario'
    report = {'run_id': manifest['run_id'], 'scenario': manifest['scenario'],
              'status': manifest.get('status'), 'app_events': app_events,
              'malformed_event_lines': malformed, 'attribution_snapshots': snapshots,
              'device_cleanup': 'inconclusive: correlate audio, attribution and suspend trace manually',
              'causality': 'No automatic causal or battery-life conclusion. A release record describes app code; an attribution timer does not establish effective suspend blocking.',
              'limitations': ['Raw system snapshots and traces are private.',
                              'The initial baseline is screen-on; only the idle scenario provides a matched screen-off control.',
                              'Trace markers and clock alignment must be verified in Perfetto.',
                              'No trace-level absence, data-loss, or suspend inference is performed by this summary.']}
    (directory / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    summary = report['app_events']
    (directory / 'report.md').write_text(
        f"# Playback ownership capture\n\nRun: `{report['run_id']}`; scenario: `{report['scenario']}`; capture: `{report['status']}`.\n\n"
        f"App records: {summary['events']} events, {summary['players_created']} creates, {summary['release_completions']} completed releases. "
        f"Owner evidence: `{summary['app_owner_evidence']}`.\n\n"
        + '\n'.join(f'- {issue}' for issue in summary['issues'])
        + '\n\nDevice cleanup: **inconclusive** until audio, attribution, and suspend evidence is correlated.\n\n'
        + report['causality'] + '\n\nSee report.json for filtered cumulative AudioMix entries. Raw artifacts require manual privacy review before sharing.\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    generate(parser.parse_args().directory)
