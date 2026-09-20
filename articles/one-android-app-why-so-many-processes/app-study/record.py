"""Bounded, read-only stock-ADB process recorder. Raw results stay local."""
import argparse
import csv
import datetime as dt
import hashlib
import json
import pathlib
import re
import shlex
import subprocess
import time

FIELDS = ('VmRSS', 'RssAnon', 'RssFile', 'RssShmem', 'VmSwap')
CONTROLS = ('memory.current', 'memory.swap.current', 'memory.high',
            'memory.swap.high', 'memory.swap.max', 'memory.events', 'cgroup.freeze')


def process_identity(stat):
    try:
        return int(stat[stat.rindex(')') + 2:].split()[19])
    except (ValueError, IndexError):
        return None


def parse_status(raw):
    return {key: int(m.group(1)) if (m := re.search(
        rf'^{key}:\s+(\d+) kB$', raw, re.M)) else None for key in FIELDS}


def parse_ps(raw):
    result = []
    for line in raw.splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit():
            result.append(dict(pid=int(fields[0]), uid=int(fields[1]), name=fields[2]))
    return result


def sum_complete(rows, field):
    values = [row.get(field) for row in rows]
    return sum(values) if values and all(v is not None for v in values) else None


def parse_sections(raw):
    result = {}
    current = None
    for line in raw.splitlines():
        if line.startswith('@@ '):
            current = line[3:]
            result[current] = ''
        elif current is not None:
            result[current] += line + '\n'
    return result


def parse_control(key, value):
    if re.fullmatch(r'-?\d+', value):
        return int(value)
    if value == 'max':
        return 'max'
    if key == 'memory.events' and re.fullmatch(r'(\w+ \d+\n?)+', value):
        return {name: int(count) for name, count in (line.split() for line in value.splitlines())}
    return None


class Recorder:
    def __init__(self, serial, package, output):
        self.serial, self.package, self.output = serial, package, output
        output.mkdir(parents=True, exist_ok=False)
        (output / 'recorder-source.py').write_bytes(pathlib.Path(__file__).read_bytes())
        self.raw = (output / 'raw.jsonl').open('x')

    def adb(self, command, timeout=20):
        start = time.monotonic()
        try:
            p = subprocess.run(['adb', '-s', self.serial, 'shell', command],
                               capture_output=True, text=True, timeout=timeout)
            out = dict(stdout=p.stdout, stderr=p.stderr, returncode=p.returncode)
        except subprocess.TimeoutExpired as exc:
            def decode(value):
                return value.decode(errors='replace') if isinstance(value, bytes) else value or ''
            out = dict(stdout=decode(exc.stdout), stderr=decode(exc.stderr),
                       returncode=None, error='timeout')
        out.update(command=command, utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                   start_monotonic=start, duration_s=time.monotonic()-start)
        self.raw.write(json.dumps(out) + '\n')
        self.raw.flush()
        if out['returncode'] != 0:
            raise RuntimeError(f'ADB failed: {out.get("error", out["stderr"])}')
        return out['stdout']

    def snapshot(self, label, rows):
        directory = self.output / 'snapshots' / label
        directory.mkdir(parents=True)
        commands = {'services': f'dumpsys activity services {self.package}',
                    'processes': f'dumpsys activity processes {self.package}',
                    'exits': f'dumpsys activity exit-info {self.package}',
                    'battery': 'dumpsys battery',
                    'thermal': 'dumpsys thermalservice'}
        for row in rows:
            commands[f'meminfo-{row["pid"]}'] = f'dumpsys meminfo {row["pid"]}'
        for name, command in commands.items():
            (directory / f'{name}.txt').write_text(self.adb(command))

    def sample(self, uid):
        package = self.package
        raw_ps = self.adb("ps -A -o PID,UID,NAME | awk 'NR==1 || $2==" + str(uid)
                          + ' || $3=="' + package + '" || index($3,"' + package
                          + ':")==1'
                          + ' || index($3,"' + package + '_")==1'
                          + ' {print}' + "'")
        processes = parse_ps(raw_ps)
        program = '''
function emit(label, path, line, rc) {
    print "@@ " label;
    while ((rc = (getline line < path)) > 0) print line;
    if (rc < 0) print "missing or unreadable";
    close(path);
}
BEGIN {
    n = split(pids, ids, " ");
    k = split("stat status oom_score_adj cgroup", keys, " ");
    c = split(controls, counters, " ");
    for (i=1; i<=n; i++) {
        pid=ids[i]; base="/proc/" pid "/";
        for (j=1; j<=k; j++) emit(pid "/" keys[j], base keys[j]);
        cg="";
        while ((getline line < (base "cgroup")) > 0) {
            if (line ~ /^0::/) cg=substr(line,4);
        }
        close(base "cgroup");
        if (cg != "") for (j=1; j<=c; j++)
            emit(pid "/" counters[j], "/sys/fs/cgroup" cg "/" counters[j]);
        emit(pid "/stat_end", base "stat");
    }
}'''
        command = ('awk -v pids=' + shlex.quote(' '.join(str(row['pid']) for row in processes))
                   + ' -v controls=' + shlex.quote(' '.join(CONTROLS)) + ' ' + shlex.quote(program))
        sections = parse_sections(self.adb(command)) if processes else {}
        for row in processes:
            pid = row['pid']
            get = lambda key: sections.get(f'{pid}/{key}', '')
            start, end = process_identity(get('stat')), process_identity(get('stat_end'))
            row.update(parse_status(get('status')))
            row.update(start_ticks=start, identity_verified=start is not None and start == end,
                       association='package_name_or_uid; service evidence in snapshots',
                       cgroup=get('cgroup').strip(), errors={})
            if not row['identity_verified']:
                row.update({key: None for key in FIELDS})
                row['errors']['identity'] = 'missing or changed during sweep'
            for key in FIELDS:
                if row[key] is None:
                    row['errors'][key] = 'missing, unreadable, or unstable identity'
            for key in ('oom_score_adj',) + CONTROLS:
                value = get(key).strip()
                row[key] = parse_control(key, value) if row['identity_verified'] else None
                if row[key] is None:
                    row['errors'][key] = value or 'not available'
        return processes


def run(args):
    recorder = Recorder(args.serial, args.package, args.output)
    outcome = {'valid_for_article_statistics': False, 'kind': 'capability_passive_pilot'}
    try:
        package = recorder.adb(f'pm list packages -U --user 0 {args.package}')
        match = re.search(rf'package:{re.escape(args.package)} uid:(\d+)', package)
        if not match:
            raise RuntimeError('Target package not found for user 0')
        metadata = dict(package=args.package, serial=args.serial, uid=int(match[1]),
                        utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                        recorder_sha256=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
                        requested_interval_s=args.interval, duration_s=args.seconds,
                        coverage='Name/UID candidates, service records retained for review; partial until audited',
                        actions='None: no launch, force-stop, gestures, or setting changes')
        for key, command in {
            'build': 'getprop ro.build.fingerprint', 'boot_id': 'cat /proc/sys/kernel/random/boot_id',
            'package_info': f'dumpsys package {args.package}',
            'limiter': 'cmd activity memory-limiter status', 'battery': 'dumpsys battery',
            'memory': 'cat /proc/meminfo', 'screen': 'dumpsys window policy',
            'settings': 'settings get system screen_off_timeout; settings get system screen_brightness',
        }.items():
            metadata[key] = recorder.adb(command)
        (args.output / 'metadata.json').write_text(json.dumps(metadata, indent=2))
        battery = re.search(r'temperature:\s*(\d+)', metadata['battery'])
        if not battery or int(battery[1]) >= 380:
            raise RuntimeError('Temperature missing or above safety threshold')
        rows = recorder.sample(metadata['uid'])
        recorder.snapshot('before', rows)
        started = time.monotonic()
        durations = []
        with (args.output / 'processes.jsonl').open('x') as stream, (args.output / 'samples.csv').open('x') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=['sweep_start_s', 'sweep_end_s', 'pid',
                                                       'start_ticks', *FIELDS])
            writer.writeheader()
            while time.monotonic() - started < args.seconds:
                begin = time.monotonic()
                rows = recorder.sample(metadata['uid'])
                end = time.monotonic()
                durations.append(end-begin)
                record = dict(sweep_start_s=begin-started, sweep_end_s=end-started,
                              utc=dt.datetime.now(dt.timezone.utc).isoformat(), processes=rows)
                stream.write(json.dumps(record) + '\n')
                stream.flush()
                for row in rows:
                    writer.writerow({key: record[key] if key.startswith('sweep_') else row.get(key)
                                     for key in writer.fieldnames})
                csvfile.flush()
                if len(durations) % 10 == 0:
                    thermal = recorder.adb('dumpsys battery')
                    temp = re.search(r'temperature:\s*(\d+)', thermal)
                    if not temp or int(temp[1]) >= 380:
                        raise RuntimeError('Thermal safety stop')
                time.sleep(max(0, args.interval - (time.monotonic()-begin)))
        recorder.snapshot('after', rows)
        outcome.update(status='complete', sweeps=len(durations),
                       median_sweep_s=sorted(durations)[len(durations)//2],
                       max_sweep_s=max(durations), final_process_count=len(rows))
    except (Exception, KeyboardInterrupt) as exc:
        outcome.update(status='invalid', error=str(exc))
    finally:
        recorder.raw.close()
        (args.output / 'outcome.json').write_text(json.dumps(outcome, indent=2))
        files = sorted(path for path in args.output.rglob('*') if path.is_file())
        (args.output / 'manifest.sha256').write_text('\n'.join(
            hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + str(path.relative_to(args.output))
            for path in files) + '\n')
    print(json.dumps(outcome, indent=2))
    return 0 if outcome['status'] == 'complete' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--package', default='com.android.chrome')
    parser.add_argument('--output', required=True, type=pathlib.Path)
    parser.add_argument('--seconds', type=int, default=30, choices=range(1, 301))
    parser.add_argument('--interval', type=float, default=1)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9_.]+', args.package) or args.interval < 1:
        parser.error('Invalid package or interval below one second')
    raise SystemExit(run(args))
