"""Index smali and group declared boundaries without inferring architecture motives."""
import argparse
import json
from pathlib import Path

def build_index(job):
    models = json.loads((job/'manifests.json').read_text())
    groups = {}
    for model in models:
        for component in model['components']:
            groups.setdefault(component['effective_process'] or 'UNRESOLVED', []).append(
                dict(split=model['split'], artifact_sha256=model['artifact_sha256'], **component))
    classes = []
    for path in sorted((job/'decoded').rglob('*.smali')):
        lines = path.read_text().splitlines()
        classes.append(dict(path=str(path.relative_to(job)),
            declaration=next((line for line in lines if line.startswith('.class ')), None),
            superclass=next((line for line in lines if line.startswith('.super ')), None),
            methods=[dict(line=i, declaration=line) for i,line in enumerate(lines,1) if line.startswith('.method ')]))
    return groups, classes

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', type=Path)
    args = parser.parse_args()
    groups, classes = build_index(args.job)
    (args.job/'process-boundaries.json').write_text(json.dumps(groups,indent=2))
    (args.job/'code-index.json').write_text(json.dumps(classes,indent=2))
    print(json.dumps(dict(declared_process_labels=len(groups),smali_classes=len(classes))))
