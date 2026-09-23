#!/usr/bin/env python3
"""Capture one sample-only trial. All raw output is private; no device tests run on import."""
import argparse
import datetime
import importlib.util
import json
import hashlib
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import uuid

PACKAGE = 'dev.returnzero.playbacklab'
DIRECT_PACKAGE = 'dev.returnzero.directlocklab'
SCENARIOS = ['foreground', 'retained', 'background', 'paused', 'idle', 'direct-untimed', 'direct-timed']


def package_for(scenario, requested=None):
    expected = DIRECT_PACKAGE if scenario.startswith('direct-') else PACKAGE
    if requested and requested != expected:
        raise ValueError(f'{scenario} requires package {expected}')
    return expected



def make_config(query, categories, duration_ms, package=PACKAGE):
    if 'linux.ftrace' not in query:
        return None
    available = {m.group(1) for m in re.finditer(r'^\s*(\w+)\s+-', categories, re.M)}
    chosen = sorted(available.intersection({'audio', 'power', 'am'}))
    lines = ['buffers { size_kb: 32768 fill_policy: RING_BUFFER }',
             f'duration_ms: {duration_ms}', 'write_into_file: true',
             'file_write_period_ms: 1000',
             'data_sources { config { name: "linux.ftrace" ftrace_config {',
             f'atrace_apps: "{package}"']
    lines += [f'atrace_categories: "{category}"' for category in chosen]
    # These events are requested, not asserted available; inspect trace stats on each build.
    lines += ['ftrace_events: "power/suspend_resume"', 'ftrace_events: "power/wakeup_source_activate"',
              'ftrace_events: "power/wakeup_source_deactivate"', '}}}']
    return '\n'.join(lines) + '\n'


class Capture:
    def __init__(self, args):
        self.args = args
        self.package = package_for(args.scenario, getattr(args, "package", None))
        self.trace_finished = False
        self.recording = None
        self.remote_video = None
        self.run_id = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
        self.directory = args.output.expanduser().resolve() / self.run_id
        self.directory.mkdir(parents=True, mode=0o700)
        self.private = self.directory / 'private'
        self.private.mkdir(mode=0o700)
        self.trace_pid = None
        self.remote_trace = f'/data/misc/perfetto-traces/playback-{self.run_id}.pftrace'
        self.manifest = {'run_id': self.run_id, 'scenario': args.scenario, 'package': self.package,
                         'source_commit': getattr(args, 'source_commit', None),
                         'screenrecord_disturbs_measurement': getattr(args, 'screenrecord', False), 'status': 'started',
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
            ('activity-processes', ['dumpsys', 'activity', 'processes']),
            ('battery', ['dumpsys', 'battery']),
            ('clock', ['sh', '-c', 'date +%s; cat /proc/uptime']),
        ]:
            try:
                output = self.adb('shell', *command, timeout=45, check=False)
                (self.private / f'{boundary}-{name}.txt').write_text(output)
            except subprocess.TimeoutExpired:
                self.manifest['warnings'].append(f'{boundary}/{name} timed out')
        if 'app_uid' in self.manifest:
            output = self.adb('shell', 'am', 'get-uid-state', str(self.manifest['app_uid']), check=False)
            (self.private / f'{boundary}-uid-state.txt').write_text(output)
        self.save()

    def app(self, command):
        output = self.adb('shell', 'am', 'start', '-W', '-n', self.package + '/.MainActivity',
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
        config = make_config(query, categories, duration, self.package)
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
        if self.trace_finished:
            return
        if self.trace_pid:
            self.adb('shell', 'kill', '-INT', self.trace_pid, check=False)
            time.sleep(2)
        self.adb('pull', self.remote_trace, str(self.private / 'trace.pftrace'), timeout=60, check=False)
        if not (self.private / 'trace.pftrace').exists():
            self.manifest['warnings'].append('Trace pull failed or trace unavailable')
        else:
            self.adb('shell', 'rm', '-f', self.remote_trace, check=False)

        self.trace_finished = True

    def events(self, name='events.jsonl'):
        if self.args.scenario != 'idle':
            data = self.adb('exec-out', 'run-as', self.package, 'cat', 'files/events.jsonl', check=False)
            (self.directory / name).write_text(data)

    def explicit_stop(self):
        if self.args.scenario == 'idle':
            return
        self.mark('explicit-stop-request')
        result = self.adb('shell', 'am', 'broadcast', '-a', self.package + '.STOP',
                          '-n', self.package + '/.StopReceiver', '--es', 'run_id', self.run_id,
                          '--include-stopped-packages', check=False)
        (self.private / 'stop-broadcast.txt').write_text(result)
        self.mark('explicit-stop')
        self.manifest['warnings'].append('Stop broadcast receipt is not release proof; inspect app release events.')

    def validate_started(self):
        if self.args.scenario == 'idle':
            self.manifest['start_verified'] = 'idle_no_app_started'
            return
        self.events('events-before-home.jsonl')
        events = []
        for line in (self.directory / 'events-before-home.jsonl').read_text().splitlines():
            try:
                event = json.loads(line)
                if isinstance(event, dict) and event.get('run_id') == self.run_id:
                    events.append(event)
            except json.JSONDecodeError:
                pass
        run_started = any(event.get('event') == 'run_start' for event in events)
        if self.args.scenario.startswith('direct-'):
            active = any(event.get('event') == 'wake_lock_acquired' and event.get('is_held') is True for event in events)
        else:
            active = any(event.get('event') == 'is_playing' and event.get('is_playing') is True for event in events)
        self.manifest['start_verified'] = bool(run_started and active)
        self.save()
        if not self.manifest['start_verified']:
            raise RuntimeError('Current-run startup events missing: cannot establish playback/lock acquisition before Home')

    def provenance(self):
        checkout = Path(__file__).resolve().parents[1]
        for key, command in [('source_checkout_head', ['rev-parse', 'HEAD']),
                             ('source_checkout_status', ['status', '--porcelain'])]:
            result = subprocess.run(['git', '-C', str(checkout), *command], capture_output=True, text=True, check=False)
            self.manifest[key] = result.stdout.strip() if result.returncode == 0 else None
        self.manifest['source_checkout_dirty'] = bool(self.manifest.get('source_checkout_status'))
        self.manifest['source_provenance_note'] = 'source_commit is operator assertion, not proof of installed APK source; installed APK hashes identify tested bytes.'
        if self.manifest['source_checkout_dirty']:
            self.manifest['warnings'].append('Source checkout contains uncommitted changes; source_commit alone does not identify tested code.')
        paths = self.adb('shell', 'pm', 'path', self.package).splitlines()
        hashes = []
        for line in paths:
            if line.startswith('package:'):
                remote = line[len('package:'):].strip()
                output = self.adb('shell', 'sha256sum', remote, check=False).strip()
                digest = output.split()[0] if output else ''
                if re.fullmatch('[a-fA-F0-9]{64}', digest):
                    hashes.append({'path': remote, 'sha256': digest.lower()})
        self.manifest['installed_apks'] = hashes
        apk = getattr(self.args, 'apk', None)
        if apk:
            digest = hashlib.sha256(apk.read_bytes()).hexdigest()
            self.manifest['supplied_apk_sha256'] = digest
            if digest not in [item['sha256'] for item in hashes]:
                raise RuntimeError('Supplied APK does not match installed package APK hash')
        if not hashes:
            self.manifest['warnings'].append('Installed APK hash unavailable')

    def start_recording(self):
        if not getattr(self.args, 'screenrecord', False):
            return
        self.remote_video = f'/sdcard/lab-{self.run_id}.mp4'
        self.mark('screenrecord-start')
        with (self.private / 'screenrecord-errors.txt').open('w') as errors:
            self.recording = subprocess.Popen(['adb', '-s', self.args.serial, 'shell',
                'screenrecord', '--time-limit', '180', self.remote_video], stdout=subprocess.DEVNULL,
                stderr=errors)
        self.manifest['warnings'].append('Screen recording perturbs measurement and is limited to 180 seconds.')

    def finish_recording(self):
        if self.recording is None:
            return
        try:
            # Only signal the PID whose command line contains our unique output path.
            processes = self.adb('shell', 'ps', '-A', '-o', 'PID,ARGS', check=False)
            for line in processes.splitlines():
                parts = line.split(None, 1)
                if len(parts) == 2 and parts[0].isdigit() and self.remote_video in parts[1] and 'screenrecord' in parts[1]:
                    self.adb('shell', 'kill', '-INT', parts[0], check=False)
            code = self.recording.wait(timeout=10)
            if code:
                self.manifest['warnings'].append(f'Screenrecord exited with status {code}; inspect recording errors.')
            self.adb('pull', self.remote_video, str(self.private / 'demonstration.mp4'), timeout=60, check=False)
            if (self.private / 'demonstration.mp4').exists() and (self.private / 'demonstration.mp4').stat().st_size:
                self.adb('shell', 'rm', '-f', self.remote_video, check=False)
            else:
                self.manifest['warnings'].append('Screen recording unavailable: output pull failed.')
        finally:
            if self.recording.poll() is None:
                self.recording.terminate()
            self.recording = None
            self.mark('screenrecord-end')

    def index_artifacts(self):
        entries = []
        for path in sorted(self.directory.rglob('*')):
            if path.is_file() and path.name not in ('artifact-index.json', 'manifest.json'):
                digest = hashlib.sha256()
                with path.open('rb') as source:
                    for block in iter(lambda: source.read(1024 * 1024), b''):
                        digest.update(block)
                entries.append({'path': str(path.relative_to(self.directory)), 'bytes': path.stat().st_size,
                                'sha256': digest.hexdigest()})
        (self.directory / 'artifact-index.json').write_text(json.dumps(entries, indent=2) + '\n')

    def run(self):
        print(f'Private run directory: {self.directory}', flush=True)
        started = False
        try:
            self.adb('get-state')
            self.adb('shell', 'input', 'keyevent', 'KEYCODE_WAKEUP')
            if self.args.scenario != 'idle':
                self.unlocked()
            uid_text = self.adb('shell', 'cmd', 'package', 'list', 'packages', '-U', self.package)
            match = re.search(rf'package:{re.escape(self.package)}\s+uid:(\d+)', uid_text)
            if not match:
                raise RuntimeError('Sample package not installed or UID unavailable')
            self.manifest['app_uid'] = int(match.group(1))
            props = {}
            for prop in ['ro.product.model', 'ro.build.version.sdk', 'ro.build.fingerprint', 'ro.build.version.security_patch']:
                props[prop] = self.adb('shell', 'getprop', prop).strip()
            self.manifest['device'] = props
            for name, cmd in [('package', ['dumpsys', 'package', self.package]), ('battery', ['dumpsys', 'battery'])]:
                (self.private / f'environment-{name}.txt').write_text(self.adb('shell', *cmd))
            self.provenance()
            self.mark('isolation-force-stop')
            for package in (PACKAGE, DIRECT_PACKAGE):
                self.adb('shell', 'am', 'force-stop', package)
            self.start_trace()
            self.snapshots('baseline-start')
            time.sleep(self.args.baseline_seconds)
            self.snapshots('baseline-end')
            started = True
            self.start_recording()
            if self.args.scenario != 'idle':
                self.app('start')
            self.mark('play-start')
            time.sleep(self.args.play_seconds)
            self.validate_started()
            self.snapshots('play-end')
            self.adb('shell', 'input', 'keyevent', 'KEYCODE_HOME')
            self.adb('shell', 'input', 'keyevent', 'KEYCODE_SLEEP')
            self.mark('quiet-screen-off-start')
            time.sleep(self.args.observe_seconds)
            self.mark('quiet-screen-off-end')
            self.snapshots('observe-end')
            self.events('events-before-cleanup.jsonl')
            self.finish_recording()
            if getattr(self.args, 'bugreport', False):
                self.finish_trace()
                self.mark('bugreport-start')
                self.manifest['warnings'].append('Bugreport perturbs device after observation and before explicit cleanup; deadline may execute meanwhile.')
                self.adb('bugreport', str(self.private / 'bugreport.zip'), timeout=300)
                self.mark('bugreport-end')
            self.explicit_stop()
            time.sleep(self.args.cleanup_seconds)
            self.snapshots('cleanup-end')
            self.manifest['status'] = 'completed'
        except BaseException as error:
            self.manifest['status'] = 'interrupted' if isinstance(error, KeyboardInterrupt) else 'failed'
            self.manifest['error'] = str(error)
            raise
        finally:
            # Force-stop guarantees test-owned background work ends even behind secure keyguard.
            for action in ['events', 'force-stop', 'trace', 'recording']:
                try:
                    if action == 'events' and started:
                        self.events()
                    elif action == 'force-stop':
                        self.mark('harness-force-stop')
                        self.adb('shell', 'am', 'force-stop', self.package, check=False)
                    elif action == 'trace':
                        self.finish_trace()
                    elif action == 'recording':
                        self.finish_recording()
                except Exception as error:
                    self.manifest['warnings'].append(f'{action}: {error}')
            self.save()
            for name in ('report', 'issue_report'):
                try:
                    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / f'analysis/{name}.py')
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    module.generate(self.directory)
                except Exception as error:
                    self.manifest['warnings'].append(f'{name} generation failed: {error}')
            self.save()
            self.index_artifacts()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--output', type=Path, default=Path.home() / 'playback-lab-captures')
    parser.add_argument('--scenario', required=True, choices=SCENARIOS)
    for name, value in [('baseline', 15), ('play', 30), ('observe', 180), ('cleanup', 15)]:
        parser.add_argument(f'--{name}-seconds', type=float, default=value)
    parser.add_argument('--package', help='Optional explicit package; must match selected scenario')
    parser.add_argument('--screenrecord', action='store_true', help='Demonstration only; disturbs measurement, 180-second video cap')
    parser.add_argument('--bugreport', action='store_true', help='Collect private bugreport after observation, before cleanup')
    parser.add_argument('--source-commit', help='Commit used to build installed APK; recorded assertion')
    parser.add_argument('--apk', type=Path, help='Verify this APK hash matches the installed package')
    args = parser.parse_args()
    try:
        package_for(args.scenario, args.package)
    except ValueError as error:
        parser.error(str(error))
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
