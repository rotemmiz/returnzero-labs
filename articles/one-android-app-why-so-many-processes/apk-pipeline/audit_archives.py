"""Audit archive ABI payloads; preserve original files and generate a research registry."""
import argparse
import hashlib
import io
import json
import os
import zipfile
from pathlib import Path

ROOT = Path(os.environ.get('RETURNZERO_APK_WORK_DIR', Path.home() / 'Downloads/apk-temps'))

def audit(path):
    abis=set()
    checked=0
    anomalies=[]
    def inspect(apk):
        nonlocal checked
        for name in apk.namelist():
            if name.startswith('lib/') and name.endswith('.so'):
                abis.add(name.split('/')[1])
                if name.startswith('lib/arm64-v8a/'):
                    with apk.open(name) as stream: header=stream.read(20)
                    if header[:6]!=b'\x7fELF\x02\x01' or int.from_bytes(header[18:20],'little')!=183:
                        anomalies.append(name)
                        continue
                    checked+=1
    with zipfile.ZipFile(path) as archive:
        if archive.testzip(): raise ValueError('CRC failure')
        if 'AndroidManifest.xml' in archive.namelist():
            kind='apk'
            inspect(archive)
        else:
            kind='xapk'
            for name in archive.namelist():
                if name.endswith('.apk'):
                    with zipfile.ZipFile(io.BytesIO(archive.read(name))) as apk:
                        if apk.testzip(): raise ValueError('Nested CRC failure')
                        inspect(apk)
    return dict(path=str(path),container=kind,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),abis=sorted(abis),verified_aarch64_libraries=checked,non_elf_arm64_entries=anomalies,eligible_for_arm64_analysis=checked>0 and not anomalies)

if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    root = parser.parse_args().root
    replacement=root/'downloads/whatsapp-arm64.xapk.part'
    if replacement.exists():
        result=audit(replacement)
        if not result['eligible_for_arm64_analysis']: raise ValueError('Replacement lacks ARM64')
        destination=replacement.with_suffix('')
        if destination.exists(): raise ValueError('Will not overwrite existing archive')
        replacement.rename(destination)
    results=[audit(path) for path in sorted((root/'downloads').glob('*.xapk'))]
    (root/'abi-audit.json').write_text(json.dumps(results,indent=2)+'\n')
    for result in results: print(Path(result['path']).name,result['abis'],result['eligible_for_arm64_analysis'])
