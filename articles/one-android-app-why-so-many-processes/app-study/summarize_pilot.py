"""Exploratory per-process plots, not cross-app memory rankings."""
import argparse
import hashlib
import json
import pathlib
import statistics

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from record import sum_complete


def summarize(root):
    metadata = json.loads((root / 'metadata.json').read_text()) if (root / 'metadata.json').exists() else {}
    app = metadata.get('app', 'chrome')
    samples = [json.loads(line) for line in (root / 'processes.jsonl').read_text().splitlines()]
    actions = [json.loads(line) for line in (root / 'actions.jsonl').read_text().splitlines()]
    derived = root / 'derived'
    derived.mkdir(exist_ok=True)
    identities = sorted({(row['pid'], row['start_ticks']) for sample in samples
                         for row in sample['processes'] if row['identity_verified']})
    stages = {}
    for sample in samples:
        stages.setdefault(sample['stage'], []).append(sample)
    summary = {}
    for stage, data in stages.items():
        rss = [sum_complete(sample['processes'], 'VmRSS') for sample in data]
        swap = [sum_complete(sample['processes'], 'VmSwap') for sample in data]
        summary[stage] = dict(samples=len(data),
            complete_rss_samples=sum(v is not None for v in rss),
            complete_vmswap_samples=sum(v is not None for v in swap),
            process_count_range=[min(len(s['processes']) for s in data), max(len(s['processes']) for s in data)],
            median_summed_rss_mib=statistics.median(v/1024 for v in rss if v is not None) if any(v is not None for v in rss) else None,
            median_summed_vmswap_mib=statistics.median(v/1024 for v in swap if v is not None) if any(v is not None for v in swap) else None)
    report = dict(warning='Exploratory warm-session pilot; RSS double-counts shared pages. '
                  'Candidate attribution is partial; missing intervals are gaps, not zeros. '
                  'VmSwap is private anonymous swap, not compressed physical swap size.',
                  stages=summary, identities=identities,
                  maximum_sample_gap_s=max(b['sweep_start_s']-a['sweep_end_s']
                      for a,b in zip(samples,samples[1:])))
    (derived / 'summary.json').write_text(json.dumps(report, indent=2))
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True, layout='constrained')
    times = [s['sweep_start_s'] for s in samples]
    for index, (pid, start) in enumerate(identities):
        xx, yy = [], []
        for sample in samples:
            match = next((r for r in sample['processes'] if r['pid']==pid and r['start_ticks']==start
                          and r['identity_verified']), None)
            if xx and sample['sweep_start_s']-xx[-1] > 3:
                xx.append(sample['sweep_start_s']-.01); yy.append(float('nan'))
            xx.append(sample['sweep_start_s'])
            yy.append(match['VmRSS']/1024 if match and match['VmRSS'] is not None else float('nan'))
        axes[0].plot(xx, yy, label=str(pid), linewidth=1)
        axes[2].plot(times, [index if any(r['pid']==pid and r['start_ticks']==start
                            for r in s['processes']) else float('nan') for s in samples],
                     '.', markersize=2)
    for field, label in [('VmRSS', 'Summed RSS (shared pages counted repeatedly)'), ('VmSwap', 'Summed VmSwap')]:
        xx, yy = [], []
        for sample in samples:
            if xx and sample['sweep_start_s']-xx[-1] > 3:
                xx.append(sample['sweep_start_s']-.01); yy.append(float('nan'))
            xx.append(sample['sweep_start_s'])
            value = sum_complete(sample['processes'], field)
            yy.append(value/1024 if value is not None else float('nan'))
        axes[1].plot(xx, yy, label=label)
    for event in actions:
        if event['stage'] in ('open-study-tab', 'open-study-place', 'home', f'resume-{app}'):
            for axis in axes:
                axis.axvline(event['elapsed_s'], color='grey', linestyle='--', alpha=.6)
            axes[0].text(event['elapsed_s'], 1.01, event['stage'], transform=axes[0].get_xaxis_transform(), fontsize=8)
    axes[0].set_ylabel('Per-process RSS (MiB)')
    axes[0].legend(title='PID', ncol=5, fontsize=8)
    axes[1].set_ylabel('Candidate totals (MiB)')
    axes[1].legend(fontsize=8)
    axes[2].set_yticks(range(len(identities)), [str(pid) for pid,_ in identities])
    axes[2].set_ylabel('Observed PID presence')
    axes[2].set_xlabel('Elapsed seconds; snapshot gaps are not interpolated in memory traces')
    journey = 'page, scrolling' if app == 'chrome' else 'place, panning'
    fig.suptitle(f'{app.title()} warm-session pilot: {journey}, Home, resume\nPartial candidate set · single run · not physical app RAM', fontsize=13)
    fig.savefig(derived / 'pilot-timeline.png', dpi=150)
    plt.close(fig)
    if (root / 'outcome.json').exists():
        (root / 'manifest.sha256').write_text('\n'.join(
            hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + str(path.relative_to(root))
            for path in sorted(root.rglob('*')) if path.is_file() and path.name != 'manifest.sha256') + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=pathlib.Path)
    summarize(parser.parse_args().root)
