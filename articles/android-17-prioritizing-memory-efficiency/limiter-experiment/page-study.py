"""Bounded page-type pilot. Run with --device SERIAL --limit TOKEN.

TOKEN must be calibrated against the device's am help and actual cgroup values.
The file workload uses a pre-provisioned, synced 512 MiB file at /data/local/tmp/limiter-pages.bin.
This pilot does not change global limiter settings or claim causal kill attribution.
"""
import argparse
import csv
import datetime
import json
import pathlib
import subprocess
import time

PKG = 'com.returnzero.limiter'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--device', required=True)
    parser.add_argument('--limit', required=True)
    parser.add_argument('--mode', choices=['anon', 'file', 'dirty'], default='anon')
    args = parser.parse_args()
    root = pathlib.Path(__file__).parent / 'results' / datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    root.mkdir(parents=True)
    def adb(*words):
        result = subprocess.run(['adb', '-s', args.device, *words], capture_output=True, text=True, timeout=15)
        with (root / 'raw.jsonl').open('a') as output:
            output.write(json.dumps({'time': time.time(), 'command': words, 'stdout': result.stdout, 'stderr': result.stderr, 'code': result.returncode}) + '\n')
        if result.returncode and words[:2] != ('shell', 'pidof'):
            result.check_returncode()
        return result.stdout.strip()
    status = adb('shell', 'am', 'memory-limiter', 'status')
    if 'disabled' in status or 'enabled' not in status:
        raise RuntimeError('Limiter inactive; no trial performed')
    (root / 'metadata.json').write_text(json.dumps({'serial': args.device, 'mode': args.mode, 'limit': args.limit, 'status': status, 'fingerprint': adb('shell', 'getprop', 'ro.build.fingerprint')}, indent=2))
    adb('shell', 'am', 'force-stop', PKG)
    adb('shell', 'am', 'start', '-n', PKG + '/.MainActivity')
    time.sleep(3)
    pid = adb('shell', 'pidof', PKG + ':heavy')
    if not pid.isdigit():
        raise RuntimeError('Expected one worker PID')
    try:
        adb('shell', 'am', 'memory-limiter', 'manual', pid, args.limit)
        group = adb('shell', 'cat', '/proc/' + pid + '/cgroup').split('0::')[-1].strip()
        adb('shell', 'cat', '/sys/fs/cgroup' + group + '/memory.high')
        adb('shell', 'cat', '/sys/fs/cgroup' + group + '/memory.swap.high')
        adb('shell', 'am', 'startservice', '-n', PKG + '/.HeavyService', '--ei', 'mode', str(['anon', 'file', 'dirty'].index(args.mode)), '--ei', 'total_mb', '256', '--es', 'path', '/data/local/tmp/limiter-pages.bin')
        start = time.monotonic()
        with (root / 'samples.csv').open('w') as output:
            writer = csv.DictWriter(output, fieldnames=['seconds', 'VmRSS', 'RssAnon', 'RssFile', 'RssShmem', 'VmSwap'])
            writer.writeheader()
            while time.monotonic() - start < 60:
                if adb('shell', 'pidof', PKG + ':heavy') != pid:
                    break
                raw = adb('shell', 'cat', '/proc/' + pid + '/status')
                adb('shell', 'cat', '/sys/fs/cgroup' + group + '/memory.events')
                row = {'seconds': time.monotonic() - start}
                for line in raw.splitlines():
                    name, _, value = line.partition(':')
                    if name in writer.fieldnames:
                        row[name] = int(value.split()[0])
                writer.writerow(row)
                output.flush()
                time.sleep(.5)
    finally:
        try:
            adb('shell', 'am', 'memory-limiter', 'manual', pid, 'none')
        finally:
            adb('shell', 'dumpsys', 'activity', 'exit-info', PKG)
            adb('shell', 'pidof', PKG)
            adb('shell', 'am', 'force-stop', PKG)
    print(root)

if __name__ == '__main__':
    main()
