"""Visible warm-session Chrome or Maps pilot; not a publication trial."""
import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import time

from record import Recorder

ROOT = pathlib.Path(__file__).parent
URL = 'https://source.android.com/docs/core/perf/memory-limiter'


def main(app='chrome'):
    package = 'com.android.chrome' if app == 'chrome' else 'com.google.android.apps.maps'
    url = URL if app == 'chrome' else 'geo:0,0?q=Eiffel%20Tower%20Paris'
    output = ROOT / 'results' / (dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + f'-{app}-visible-pilot')
    recorder = Recorder('46121FDAS007NL', package, output)
    (output / 'pilot-source.py').write_bytes(pathlib.Path(__file__).read_bytes())
    actions = (output / 'actions.jsonl').open('x')
    samples = (output / 'processes.jsonl').open('x')
    start = time.monotonic()
    outcome = dict(kind='warm_session_visible_pilot', valid_for_article_statistics=False,
                   coverage='name/UID candidates; service attribution pending audit')

    def marker(stage, command=None):
        event = dict(stage=stage, elapsed_s=time.monotonic()-start,
                     utc=dt.datetime.now(dt.timezone.utc).isoformat(), command=command)
        actions.write(json.dumps(event) + '\n')
        actions.flush()
        print(stage, flush=True)
        if command:
            recorder.adb(command)

    def safety():
        raw = recorder.adb('dumpsys battery')
        temp = re.search(r'temperature:\s*(\d+)', raw)
        if not temp or int(temp[1]) >= 380:
            raise RuntimeError('Thermal guard')

    def observe(stage, seconds):
        marker(stage)
        deadline = time.monotonic() + seconds
        count = 0
        while time.monotonic() < deadline:
            begin = time.monotonic()
            rows = recorder.sample(uid)
            samples.write(json.dumps(dict(stage=stage, sweep_start_s=begin-start,
                               sweep_end_s=time.monotonic()-start, processes=rows)) + '\n')
            samples.flush()
            count += 1
            if count % 10 == 0:
                safety()
            time.sleep(max(0, 1-(time.monotonic()-begin)))

    def snapshot(stage):
        marker(stage + '-snapshot-start')
        recorder.snapshot(stage, recorder.sample(uid))
        marker(stage + '-snapshot-end')

    try:
        safety()
        state = recorder.adb('dumpsys window policy')
        if 'showing=true' in state or 'screenState=SCREEN_STATE_ON' not in state:
            raise RuntimeError('Unlock screen before pilot')
        packages = recorder.adb(f'pm list packages -U --user 0 {package}')
        uid = int(re.search(rf'package:{re.escape(package)} uid:(\d+)', packages)[1])
        metadata = dict(url=url, app=app, uid=uid, baseline='existing warm session; no force-stop',
                        build=recorder.adb('getprop ro.build.fingerprint'),
                        boot_id=recorder.adb('cat /proc/sys/kernel/random/boot_id'),
                        package=recorder.adb(f'dumpsys package {package}'),
                        limiter=recorder.adb('cmd activity memory-limiter status'),
                        screen=state, started_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        (output / 'metadata.json').write_text(json.dumps(metadata, indent=2))
        print(str(output), flush=True)
        snapshot('baseline')
        observe('baseline', 30)
        extras = (' --ez create_new_tab true --es com.android.browser.application_id returnzero.memory.study'
                  if app == 'chrome' else '')
        marker('open-study-tab' if app == 'chrome' else 'open-study-place',
               f'am start -W -a android.intent.action.VIEW -d "{url}" -p {package}' + extras)
        observe('foreground-loaded', 30)
        marker('foreground-state', 'dumpsys activity activities | grep topResumedActivity')
        for step in range(10):
            gesture = ('input swipe 500 1600 500 650 400' if app == 'chrome'
                       else ('input swipe 500 750 700 750 400' if step % 2 == 0
                             else 'input swipe 700 750 500 750 400'))
            marker(f'gesture-{step+1}', gesture)
            observe('foreground-scroll' if app == 'chrome' else 'foreground-pan', 6)
        snapshot('foreground-end')
        marker('home', 'input keyevent KEYCODE_HOME')
        observe('background-first-30', 30)
        snapshot('background-30')
        observe('background-remaining-150', 150)
        snapshot('background-end')
        marker(f'resume-{app}', 'am start -W -a android.intent.action.MAIN '
               f'-c android.intent.category.LAUNCHER -p {package}')
        observe('resumed', 30)
        snapshot('resumed-end')
        outcome.update(status='complete', cleanup='Study view left visible for verified cleanup')
    except (Exception, KeyboardInterrupt) as exc:
        outcome.update(status='invalid', error=str(exc))
    finally:
        marker('recording-stopped')
        recorder.raw.close()
        actions.close()
        samples.close()
        (output / 'outcome.json').write_text(json.dumps(outcome, indent=2))
        (output / 'manifest.sha256').write_text('\n'.join(
            hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + str(path.relative_to(output))
            for path in sorted(output.rglob('*')) if path.is_file() and path.name != 'manifest.sha256') + '\n')
        print(json.dumps(outcome), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', choices=['chrome', 'maps'], default='chrome')
    main(parser.parse_args().app)
