"""Preserve partial meminfo coverage and distinguish reported PSS from swap."""
import argparse
import json
import pathlib
import re


def parse_meminfo(raw):
    header = re.search(r'MEMINFO in pid (\d+) \[([^\]]+)\]', raw)
    fields = dict(pid=int(header[1]) if header else None,
                  name=header[2] if header else None,
                  reported_total_pss_kib=None, reported_swap_pss_kib=None,
                  reported_total_rss_kib=None, private_dirty_plus_clean_kib=None)
    for label, field in [('TOTAL PSS', 'reported_total_pss_kib'),
                         ('TOTAL RSS', 'reported_total_rss_kib'),
                         ('TOTAL SWAP PSS', 'reported_swap_pss_kib')]:
        match = re.search(rf'{label}:\s*(\d+)', raw)
        if match:
            fields[field] = int(match[1])
    total = re.search(r'^\s*TOTAL\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)', raw, re.M)
    if total and re.search(r'Pss\s+Private\s+Private\s+SwapPss\s+Rss', raw):
        fields['private_dirty_plus_clean_kib'] = int(total[2]) + int(total[3])
    fields['coverage'] = ('summary_available' if fields['reported_total_pss_kib'] is not None
                          else 'missing_summary; header alone is not a zero-memory process')
    return fields


def audit(root):
    stages = {}
    for directory in sorted((root / 'snapshots').iterdir()):
        services = (directory / 'services.txt').read_text()
        hosted = sorted(set(int(pid) for pid in re.findall(r'app=ProcessRecord\{[^ ]+ (\d+):', services)))
        records = [parse_meminfo(path.read_text()) for path in sorted(directory.glob('meminfo-*.txt'))]
        stages[directory.name] = dict(service_hosted_pids=hosted, per_process=records,
             complete_pss_for_snapshot_candidates=bool(records) and all(
                 record['reported_total_pss_kib'] is not None for record in records))
    output = root / 'derived'
    output.mkdir(exist_ok=True)
    report = dict(stages=stages, notes=[
        'Service hosting confirms association, not renderer/site ownership or developer intent.',
        'Reported Android TOTAL PSS can include SwapPss: never add the swap field again.',
        'Private dirty plus clean is a dumpsys private-footprint field, not a guaranteed physical ownership sum.',
        'Snapshot PID identity is not bracketed by start time; corroborate against adjacent lightweight samples.',
        'No aggregate PSS is emitted when any candidate lacks a summary.'])
    (output / 'snapshot-audit.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({stage: dict(hosted=value['service_hosted_pids'],
                       pss_present=sum(r['reported_total_pss_kib'] is not None for r in value['per_process']),
                       candidates=len(value['per_process'])) for stage,value in stages.items()}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=pathlib.Path)
    audit(parser.parse_args().root)
