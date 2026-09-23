#!/usr/bin/env python3
"""Run the seven-condition matrix, pausing for manual unlock between trials."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

SCENARIOS = ('idle', 'foreground', 'retained', 'background', 'paused', 'direct-untimed', 'direct-timed')


def trial_order(rounds):
    return [(repetition + 1, scenario) for repetition in range(rounds)
            for scenario in SCENARIOS[repetition % len(SCENARIOS):] + SCENARIOS[:repetition % len(SCENARIOS)]]


def checkpoint_state(checkpoint, identity):
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text())
        if any(state.get(key) != value for key, value in identity.items()):
            raise ValueError('Existing matrix has different source, rounds, device, or APKs; use a new output directory')
        return state
    return {**identity, 'attempts': [], 'protocol': {'play_seconds': 30, 'observe_seconds': 180}}


def save_checkpoint(checkpoint, state):
    temporary = checkpoint.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2) + '\n')
    temporary.replace(checkpoint)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--rounds', type=int, default=3)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error('--rounds must be positive')
    os.umask(0o077)
    root = Path(__file__).resolve().parents[1]
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    checkpoint = output / 'matrix.json'
    order = trial_order(args.rounds)
    apks = {name: root / path for name, path in {
        'playback': 'app/build/outputs/apk/debug/app-debug.apk',
        'direct': 'direct-lock/build/outputs/apk/debug/direct-lock-debug.apk',
    }.items()}
    identity = {'source_commit': args.source_commit, 'rounds': args.rounds, 'serial': args.serial,
                'apk_sha256': {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in apks.items()}}
    try:
        state = checkpoint_state(checkpoint, identity)
    except ValueError as error:
        parser.error(str(error))
    def save():
        save_checkpoint(checkpoint, state)
    for index, (repetition, scenario) in enumerate(order):
        if any(t['index'] == index and t.get('returncode') == 0 for t in state['attempts']):
            continue
        print(f'Trial {index + 1}/{len(order)}: round {repetition}, {scenario}', flush=True)
        subprocess.run(['adb', '-s', args.serial, 'shell', 'input', 'keyevent', 'KEYCODE_WAKEUP'], check=True)
        waiting = False
        while True:
            result = subprocess.run(['adb', '-s', args.serial, 'shell', 'dumpsys', 'window', 'policy'],
                                    capture_output=True, text=True, check=True)
            if not re.search(r'(?:mShowingLockscreen|isStatusBarKeyguard|showing|isKeyguardShowing)=true', result.stdout):
                break
            if not waiting:
                print('WAITING: unlock the Pixel to start this trial. No lock settings will be changed.', flush=True)
                waiting = True
            time.sleep(5)
        apk = apks['direct' if scenario.startswith('direct-') else 'playback']
        if hashlib.sha256(apk.read_bytes()).hexdigest() != identity['apk_sha256']['direct' if scenario.startswith('direct-') else 'playback']:
            parser.error('APK changed during matrix collection; use a new output directory')
        attempt = {'index': index, 'round': repetition, 'scenario': scenario,
                   'start_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   'apk_sha256': hashlib.sha256(apk.read_bytes()).hexdigest()}
        state['attempts'].append(attempt)
        save()
        before = set(output.glob('20*'))
        result = subprocess.run([sys.executable, str(root / 'capture/capture.py'), '--serial', args.serial,
                                 '--scenario', scenario, '--output', str(output), '--source-commit', args.source_commit,
                                 '--apk', str(apk), '--play-seconds', '30', '--observe-seconds', '180'])
        attempt['returncode'] = result.returncode
        attempt['run_directories'] = sorted(p.name for p in set(output.glob('20*')) - before if p.is_dir())
        attempt['end_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save()
        if result.returncode:
            raise SystemExit('Trial failed; evidence preserved. Resolve the cause and rerun the same matrix command to resume.')
    print('Matrix collection complete. Review evidence before drawing conclusions.', flush=True)


if __name__ == '__main__':
    main()
