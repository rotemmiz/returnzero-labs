#!/usr/bin/env python3
"""Capture one sample-only trial. All raw output is private; no device tests run on import."""
import argparse
import datetime
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid

PACKAGE = 'dev.returnzero.playbacklab'


def make_config(query, categories, duration_ms):
    if 'linux.ftrace' not in query:
        return None
    available = {m.group(1) for m in re.finditer(r'^\s*(\w+)\s+-', categories, re.M)}
    chosen = sorted(available.intersection({'audio', 'power', 'am'}))
    lines = ['buffers { size_kb: 32768 fill_policy: RING_BUFFER }',
             f'duration_ms: {duration_ms}', 'write_into_file: true',
             'file_write_period_ms: 1000',
             'data_sources { config { name: "linux.ftrace" ftrace_config {',
             f'atrace_apps: "{PACKAGE}"']
    lines += [f'atrace_categories: "{category}"' for category in chosen]
    # These events are requested, not asserted available; inspect trace stats on each build.
    lines += ['ftrace_events: "power/suspend_resume"', 'ftrace_events: "power/wakeup_source_activate"',
              'ftrace_events: "power/wakeup_source_deactivate"', '}}}']
    return '\n'.join(lines) + '\n'


class Capture:
    def __init__(self, args):
        self.args = args
        self.run_id = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
        self.directory = args.output.expanduser().resolve() / self.run_id
        self.directory.mkdir(parents=True, mode=0o700)
        self.private = self.directory / 'private'
        self.private.mkdir(mode=0o700)
        self.trace_pid = None
        self.remote_trace = f'/data/misc/perfetto-traces/playback-{self.run_id}.pftrace'
        self.manifest = {'run_id': self.run_id, 'scenario': args.scenario, 'status': 'started',
                         'durations': {k: getattr(args, k) for k in ('baseline_seconds', 'play_seconds', 'observe_seconds', 'cleanup_seconds')},
                         'boundaries': [], 'commands': [], 'warnings': [],
                         'privacy': 'Private raw system dumps; do not publish without redaction.',
                         'clock': 'host monotonic_ns brackets each sequential adb call; app elapsed_ns includes suspend; uptime_ms does not',
                         'settling_budget_seconds': 10, 'battery_stats_reset': False, 'baseline_screen_state': 'on',
                         'trace_event_support': 'requested events require trace-level validation; no availability inferred from config'}

    def adb(self, *command, timeout=30, check=True, binary=False, input_text=None):
        start = time.monotonic_ns()
        try:
            result = subprocess.run(['adb', '-s', self.args.serial, *command], input=input_text,
                                    capture_output=True, text=not binary, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            self.manifest['commands'].append({'command': list(command), 'start_host_ns': start,
                                              'end_host_ns': time.monotonic_ns(), 'error': 'timeout'})
            raise
        self.manifest['commands'].append({'command': list(command), 'start_host_ns': start,
                                          'end_host_ns': time.monotonic_ns(), 'returncode': result.returncode})
        if result.returncode and result.stderr:
            with (self.private / 'command-errors.txt').open('a') as errors:
                errors.write(f'{command!r}: {result.stderr}\n')
        if check and result.returncode:
            raise RuntimeError(f'adb {command[0]} failed: {str(result.stderr)[:300]}')
        return result.stdout

    def save(self):
        (self.directory / 'manifest.json').write_text(json.dumps(self.manifest, indent=2) + '\n')

    def mark(self, boundary):
        self.manifest['boundaries'].append({'boundary': boundary, 'host_monotonic_ns': time.monotonic_ns(), 'host_wall_ns': time.time_ns()})
        self.save()
        print(boundary, flush=True)

    def snapshots(self, boundary):
        self.mark(boundary)
        for name, command in [
            ('audio-flinger', ['dumpsys', 'media.audio_flinger']), ('audio', ['dumpsys', 'audio']),
            ('power', ['dumpsys', 'power']), ('batterystats', ['dumpsys', 'batterystats', '--charged']),
            ('processes', ['ps', '-A', '-o', 'UID,PID,NAME']),
        ]:
            try:
                output = self.adb('shell', *command, timeout=45, check=False)
                (self.private / f'{boundary}-{name}.txt').write_text(output)
            except subprocess.TimeoutExpired:
                self.manifest['warnings'].append(f'{boundary}/{name} timed out')
        self.save()

    def app(self, command):
        output = self.adb('shell', 'am', 'start', '-W', '-n', PACKAGE + '/.MainActivity',
                         '--es', 'command', command, '--es', 'scenario', self.args.scenario,
                         '--es', 'run_id', self.run_id)
        if 'Error:' in output or 'Exception' in output:
            raise RuntimeError(f'App command failed: {output[:400]}')

    def unlocked(self):
        state = self.adb('shell', 'dumpsys', 'window', 'policy')
        (self.private / 'keyguard-check.txt').write_text(state)
        if re.search(r'(?:mShowingLockscreen|isStatusBarKeyguard|showing|isKeyguardShowing)=true', state):
            raise RuntimeError('Unlock the phone manually before capture; keyguard is showing.')

    def start_trace(self):
        query = self.adb('shell', 'perfetto', '--query', check=False)
        categories = self.adb('shell', 'atrace', '--list_categories', check=False)
        (self.private / 'perfetto-capabilities.txt').write_text(query)
        (self.private / 'atrace-categories.txt').write_text(categories)
        supported = self.adb('shell', 'cat', '/sys/kernel/tracing/available_events', check=False)
        (self.private / 'ftrace-available-events.txt').write_text(supported)
        if not supported.strip():
            self.manifest['warnings'].append('ftrace available_events unreadable; event support unresolved')
        duration = int((sum(self.manifest['durations'].values()) + 240) * 1000)
        config = make_config(query, categories, duration)
        if config is None:
            self.manifest['warnings'].append('linux.ftrace not discovered; trace unavailable')
            return
        (self.directory / 'trace-config.pbtxt').write_text(config)
        response = self.adb('shell', 'perfetto', '--background-wait', '--txt', '-c', '-', '-o', self.remote_trace,
                            input_text=config, timeout=30, check=False)
        (self.private / 'trace-start.txt').write_text(response)
        match = re.search(r'^\s*(\d+)\s*$', response, re.M)
        if match:
            self.trace_pid = match.group(1)
        else:
            self.manifest['warnings'].append('Perfetto did not return a background PID; trace may be unavailable')

    def finish_trace(self):
        if self.trace_pid:
            self.adb('shell', 'kill', '-INT', self.trace_pid, check=False)
            time.sleep(2)
        result = self.adb('pull', self.remote_trace, str(self.private / 'trace.pftrace'), timeout=60, check=False)
        if not (self.private / 'trace.pftrace').exists():
            self.manifest['warnings'].append('Trace pull failed or trace unavailable')
        else:
            self.adb('shell', 'rm', '-f', self.remote_trace, check=False)

    def run(self):
        print(f'Private run directory: {self.directory}', flush=True)
        started = False
        try:
            self.adb('get-state')
            self.unlocked()
            uid_text = self.adb('shell', 'cmd', 'package', 'list', 'packages', '-U', PACKAGE)
            match = re.search(rf'package:{re.escape(PACKAGE)}\s+uid:(\d+)', uid_text)
            if not match:
                raise RuntimeError('Sample package not installed or UID unavailable')
            self.manifest['app_uid'] = int(match.group(1))
            props = {}
            for prop in ['ro.product.model', 'ro.build.version.sdk', 'ro.build.fingerprint', 'ro.build.version.security_patch']:
                props[prop] = self.adb('shell', 'getprop', prop).strip()
            self.manifest['device'] = props
            for name, cmd in [('package', ['dumpsys', 'package', PACKAGE]), ('battery', ['dumpsys', 'battery'])]:
                (self.private / f'environment-{name}.txt').write_text(self.adb('shell', *cmd))
            self.adb('shell', 'am', 'force-stop', PACKAGE)
            self.start_trace()
            self.snapshots('baseline-start')
            time.sleep(self.args.baseline_seconds)
            self.snapshots('baseline-end')
            started = True
            self.app('start')
            self.mark('play-start')
            time.sleep(self.args.play_seconds)
            self.snapshots('play-end')
            self.adb('shell', 'input', 'keyevent', 'KEYCODE_HOME')
            self.adb('shell', 'input', 'keyevent', 'KEYCODE_SLEEP')
            self.mark('quiet-screen-off-start')
            time.sleep(self.args.observe_seconds)
            self.mark('quiet-screen-off-end')
            self.snapshots('observe-end')
            self.adb('shell', 'input', 'keyevent', 'KEYCODE_WAKEUP')
            self.app('stop')
            self.mark('explicit-stop')
            time.sleep(self.args.cleanup_seconds)
            self.snapshots('cleanup-end')
            self.manifest['status'] = 'completed'
        except BaseException as error:
            self.manifest['status'] = 'interrupted' if isinstance(error, KeyboardInterrupt) else 'failed'
            self.manifest['error'] = str(error)
            raise
        finally:
            # Force-stop guarantees test-owned background work ends even behind secure keyguard.
            for action in ['events', 'force-stop', 'trace']:
                try:
                    if action == 'events' and started:
                        data = self.adb('exec-out', 'run-as', PACKAGE, 'cat', 'files/events.jsonl', check=False)
                        (self.directory / 'events.jsonl').write_text(data)
                    elif action == 'force-stop':
                        self.mark('harness-force-stop')
                        self.adb('shell', 'am', 'force-stop', PACKAGE, check=False)
                    elif action == 'trace':
                        self.finish_trace()
                except Exception as error:
                    self.manifest['warnings'].append(f'{action}: {error}')
            self.save()
            spec = importlib.util.spec_from_file_location('playback_report', Path(__file__).resolve().parents[1] / 'analysis/report.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.generate(self.directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--output', type=Path, default=Path.home() / 'playback-lab-captures')
    parser.add_argument('--scenario', required=True, choices=['foreground', 'retained', 'background', 'paused'])
    for name, value in [('baseline', 15), ('play', 30), ('observe', 180), ('cleanup', 15)]:
        parser.add_argument(f'--{name}-seconds', type=float, default=value)
    args = parser.parse_args()
    if any(not math.isfinite(getattr(args, name + '_seconds')) or getattr(args, name + '_seconds') < 0
           for name in ['baseline', 'play', 'observe', 'cleanup']):
        parser.error('Durations must be finite and nonnegative')
    if args.play_seconds + args.observe_seconds > 270:
        parser.error('Playback + observation must stay below the app five-minute deadline; maximum 270 seconds')
    os.umask(0o077)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    Capture(args).run()


if __name__ == '__main__':
    main()
