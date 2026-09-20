"""Acquire verified installed APK sets and inventory decoded process declarations."""
import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile

ANDROID = '{http://schemas.android.com/apk/res/android}'
ROOT = pathlib.Path(os.environ.get('RETURNZERO_APK_WORK_DIR', pathlib.Path.home() / 'Downloads/apk-temps'))


def default_apksigner():
    executable = shutil.which('apksigner')
    if executable:
        return executable
    sdk = pathlib.Path(os.environ.get('ANDROID_HOME', pathlib.Path.home() / 'Library/Android/sdk'))
    candidates = sorted((sdk / 'build-tools').glob('*/apksigner'), reverse=True)
    return str(candidates[0]) if candidates else 'apksigner'


def qualified(package, name):
    if not name:
        return None
    return package + name if name.startswith('.') else package + '.' + name if '.' not in name else name


def process_name(package, value):
    return package + value if value.startswith(':') else value


def manifest_model(xml):
    root = ET.fromstring(xml)
    package = root.attrib['package']
    app = root.find('application')
    result = dict(package=package, split=root.get('split'), version_code=root.get(ANDROID+'versionCode'), components=[])
    if app is None:
        return result
    result['application_attributes'] = {key.removeprefix(ANDROID): value for key,value in app.attrib.items()}
    default = process_name(package, app.get(ANDROID + 'process', package))
    activities = {qualified(package, x.get(ANDROID+'name')): x for x in app.findall('activity')}
    for node in app:
        if node.tag not in ('activity', 'activity-alias', 'service', 'receiver', 'provider'):
            continue
        attrs = {key.removeprefix(ANDROID): value for key,value in node.attrib.items()}
        target = activities.get(qualified(package, attrs.get('targetActivity'))) if node.tag == 'activity-alias' else None
        declared = (target.get(ANDROID+'process') if target is not None else None) if node.tag == 'activity-alias' else attrs.get('process')
        unresolved_alias = node.tag == 'activity-alias' and target is None
        effective = None if unresolved_alias else process_name(package, declared or default)
        if effective and effective.startswith('@'):
            effective = None
        result['components'].append(dict(kind=node.tag, name=qualified(package, attrs.get('name')),
            attributes=attrs, effective_process=effective,
            process_origin='alias_target' if target is not None else 'unresolved_alias' if unresolved_alias else 'component' if declared else 'application_default',
            enabled='false' if app.get(ANDROID+'enabled') == 'false' else attrs.get('enabled', app.get(ANDROID+'enabled', 'true')),
            exported=attrs.get('exported'), exported_note='explicit' if 'exported' in attrs else 'requires SDK/intent-filter interpretation',
            evidence='decoded manifest; declaration is not runtime proof'))
    return result


def apk_inventory(path):
    if path.stat().st_size == 0:
        raise ValueError('Empty APK')
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None or 'AndroidManifest.xml' not in archive.namelist():
            raise ValueError('Corrupt APK or missing manifest')
        return dict(file=path.name, bytes=path.stat().st_size,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    dex=[n for n in archive.namelist() if re.fullmatch(r'classes\d*\.dex', n)],
                    native=[n for n in archive.namelist() if n.startswith('lib/') and n.endswith('.so')])


def require_arm64(apks):
    count = 0
    non_elf_entries = []
    for apk in apks:
        with zipfile.ZipFile(apk) as archive:
            for name in archive.namelist():
                if name.startswith('lib/arm64-v8a/') and name.endswith('.so'):
                    with archive.open(name) as stream:
                        header = stream.read(20)
                    if len(header) < 20 or header[:6] != b'\x7fELF\x02\x01' or int.from_bytes(header[18:20], 'little') != 183:
                        non_elf_entries.append(dict(apk=apk.name, entry=name, note='Not treated as native code'))
                        continue
                    count += 1
    if not count:
        raise ValueError('ARM64-only study: no verified AArch64 libraries; reject 32-bit or unknown ABI input')
    return dict(verified_aarch64_libraries=count, non_elf_arm64_entries=non_elf_entries)


class Job:
    def __init__(self, output, signer):
        self.output = output
        self.signer = signer
        output.mkdir(parents=True, exist_ok=False)

    def command(self, argv):
        started = time.monotonic()
        result = subprocess.run(argv, capture_output=True, text=True, timeout=600)
        with (self.output/'commands.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(argv=argv, utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                duration_seconds=time.monotonic()-started, returncode=result.returncode, stdout=result.stdout, stderr=result.stderr))+'\n')
        if result.returncode:
            raise RuntimeError(f'Command failed ({result.returncode}): {argv[0]}; see commands.jsonl')
        return result.stdout

    def inspect(self, apks):
        if not apks:
            raise ValueError('No APKs supplied')
        abi = require_arm64(apks)
        (self.output/'abi-policy.json').write_text(json.dumps(dict(target='arm64-v8a',universal_policy='Preserve original; analyze only ARM64 native code', **abi),indent=2))
        records, models = [], []
        for index, apk in enumerate(apks):
            record = apk_inventory(apk)
            signature = self.command([self.signer, 'verify', '--print-certs', str(apk)])
            record['signer_sha256'] = re.findall(r'certificate SHA-256 digest: ([0-9a-fA-F]+)', signature)
            if not record['signer_sha256']:
                raise ValueError('No verified signer digest')
            directory = self.output/'decoded'/f'{index:02d}-{apk.stem}'
            self.command(['apktool', 'd', str(apk), '-o', str(directory)])
            model = manifest_model((directory/'AndroidManifest.xml').read_text())
            if model['version_code'] is None:
                version = re.search(r'^  versionCode: [\'\"]?(\d+)', (directory/'apktool.yml').read_text(), re.M)
                model['version_code'] = version.group(1) if version else None
            model['artifact_sha256'] = record['sha256']
            models.append(model)
            records.append(record)
        if len({m['package'] for m in models}) != 1 or len({tuple(r['signer_sha256']) for r in records}) != 1:
            raise ValueError('Inconsistent package or signer across APK set')
        bases = [m for m in models if not m['split']]
        if len(bases) != 1 or len({m['version_code'] for m in models}) != 1:
            raise ValueError('Missing/duplicate base or inconsistent version codes')
        default = process_name(bases[0]['package'], bases[0].get('application_attributes', {}).get('process', bases[0]['package']))
        for model in models:
            for component in model['components']:
                if model['split'] and component['process_origin'] == 'application_default':
                    component['effective_process'] = None if default.startswith('@') else default
        (self.output/'inventory.json').write_text(json.dumps(records, indent=2))
        (self.output/'manifests.json').write_text(json.dumps(models, indent=2))
        (self.output/'checksums.sha256').write_text('\n'.join(r['sha256']+'  originals/'+r['file'] for r in records)+'\n')


def main(args):
    args.root.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    job = Job(args.root/'jobs'/(stamp+'-'+args.mode), args.apksigner)
    originals = job.output/'originals'
    originals.mkdir()
    status = dict(stage='started', publication_ready=False)
    try:
        if args.mode == 'acquire':
            if not re.fullmatch(r'[A-Za-z0-9_.]+', args.package):
                raise ValueError('Invalid package')
            base = ['adb', '-s', args.serial, 'shell']
            def identity():
                paths = job.command(base+['pm', 'path', '--user', str(args.user), args.package])
                info = job.command(base+['dumpsys', 'package', args.package])
                versions = re.findall(r'^\s*(versionCode=\S+|versionName=\S+).*$', info, re.M)
                return dict(paths=paths, versions=versions)
            before = identity()
            paths = [line.removeprefix('package:') for line in before['paths'].splitlines() if line.startswith('package:')]
            if not paths or not before['versions']:
                raise ValueError('Package unavailable for requested user')
            for index,path in enumerate(paths):
                job.command(['adb','-s',args.serial,'pull',path,str(originals/f'{index:02d}-{pathlib.PurePosixPath(path).name}')])
            after = identity()
            (job.output/'acquisition.json').write_text(json.dumps(dict(serial=args.serial,user=args.user,package=args.package,before=before,after=after),indent=2))
            if before != after:
                raise ValueError('APK set/version changed during acquisition; preserved invalid attempt')
        else:
            for index,path in enumerate(args.apk):
                if path.suffix.lower() == '.apk':
                    shutil.copy2(path, originals/f'{index:02d}-{path.name}')
                else:
                    with zipfile.ZipFile(path) as bundle:
                        names = bundle.namelist()
                        if 'AndroidManifest.xml' in names:
                            shutil.copy2(path, originals/f'{index:02d}-{path.stem}.apk')
                            continue
                        if len(names) != len(set(names)) or sum(i.file_size for i in bundle.infolist()) > 4_000_000_000:
                            raise ValueError('Duplicate entries or oversized bundle')
                        for name in names:
                            if name.startswith('/') or '..' in pathlib.PurePosixPath(name).parts or '\\' in name:
                                raise ValueError('Unsafe archive path')
                        for split_index,name in enumerate(names):
                            if name.endswith('.apk'):
                                destination = originals/f'{index:02d}-{split_index:02d}-{pathlib.PurePosixPath(name).name}'
                                with bundle.open(name) as source, destination.open('xb') as target:
                                    shutil.copyfileobj(source,target)
                    (job.output/'bundle-source.json').write_text(json.dumps(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()),indent=2))
        (job.output/'tools.json').write_text(json.dumps(dict(apktool=job.command(['apktool','--version']).strip(),apksigner=job.command([args.apksigner,'version']).strip(),code_format='smali; JADX not installed'),indent=2))
        job.inspect(sorted(originals.glob('*.apk')))
        status.update(stage='manifest_complete', next='Trace code; runtime not tested; architecture report not yet written')
    except Exception as exc:
        status.update(stage='failed', error=str(exc))
    finally:
        (job.output/'pipeline-source.py').write_bytes(pathlib.Path(__file__).read_bytes())
        (job.output/'status.json').write_text(json.dumps(status,indent=2))
        print(json.dumps(dict(output=str(job.output), **status),indent=2))
    return 1 if status['stage']=='failed' else 0


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=pathlib.Path, default=ROOT)
    parser.add_argument('--apksigner', default=default_apksigner())
    sub=parser.add_subparsers(dest='mode',required=True)
    acquire=sub.add_parser('acquire')
    acquire.add_argument('--serial',required=True)
    acquire.add_argument('--user',type=int,default=0)
    acquire.add_argument('--package',required=True)
    inspect=sub.add_parser('inspect')
    inspect.add_argument('apk',type=pathlib.Path,nargs='+')
    raise SystemExit(main(parser.parse_args()))
