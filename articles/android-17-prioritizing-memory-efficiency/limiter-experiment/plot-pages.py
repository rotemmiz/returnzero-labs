"""Generate figures and a summary from compare-pages.py trial data."""
import csv, json, pathlib, statistics, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
root=pathlib.Path(sys.argv[1])
charts=root/"charts"; charts.mkdir(exist_ok=True)
modes=["anon","file","dirty"]
labels={"anon":"Anonymous","file":"Clean file mapping","dirty":"Private dirty mapping"}
runs={m:[] for m in modes}
for folder in sorted(root.glob("[0-9][0-9]-*")):
    if not (folder/"result.json").exists(): continue
    result=json.loads((folder/"result.json").read_text())
    if result["outcome"]!="completed": continue
    rows=list(csv.DictReader((folder/"samples.csv").open()))
    runs[result["mode"]].append((rows,result))
if not all(runs.values()):
    raise SystemExit("Need completed trials for all three modes before plotting a comparison")
fig,axes=plt.subplots(1,3,figsize=(14,4),sharey=True)
colors={"RssAnon":"#c23b42","RssFile":"#2878aa","VmSwap":"#8654a0"}
for ax,mode in zip(axes,modes):
    for index,(rows,result) in enumerate(runs[mode]):
        for metric,color in colors.items():
            ax.plot([float(r["seconds"]) for r in rows],[float(r[metric])/1024 for r in rows],color=color,alpha=.45,label=metric if index==0 else None)
    ax.set_title(labels[mode]); ax.set_xlabel("Seconds");ax.grid(alpha=.2)
axes[0].set_ylabel("MiB (process counters)")
if runs["anon"]: axes[0].legend()
fig.suptitle("Pixel page-type comparison: all recorded trials",fontsize=14)
fig.tight_layout()
for ext in ["svg","png"]: fig.savefig(charts/f"page-types.{ext}",dpi=160)
plt.close(fig)
fig,axes=plt.subplots(1,3,figsize=(14,4),sharey=True)
summary=[]
for ax,mode in zip(axes,modes):
    for rows,result in runs[mode]:
        ax.plot([float(r["seconds"]) for r in rows],[float(r["current"])/1048576 for r in rows],alpha=.6)
        ax.plot([float(r["seconds"]) for r in rows],[float(r["high"])/1048576 for r in rows],color="black",linestyle="--",alpha=.35)
    ax.plot([],[],color="black",linestyle="--",label="Observed memory.high")
    ax.set_title(labels[mode]);ax.set_xlabel("Seconds");ax.grid(alpha=.2)
    if runs[mode]:
        ends=[float(rows[-1]["current"])/1048576 for rows,_ in runs[mode]]
        events=[int(rows[-1]["high_events"])-int(rows[0]["high_events"]) for rows,_ in runs[mode]]
        entry=dict(mode=mode,trials=len(ends),current_mib_median=statistics.median(ends),current_mib_range=[min(ends),max(ends)],high_events_median=statistics.median(events),survivors=sum(r["worker_survived"] for _,r in runs[mode]))
        for metric in ["RssAnon", "RssFile", "VmSwap"]:
            values=[float(rows[-1][metric])/1024 for rows,_ in runs[mode]]
            entry[metric+"_mib_median"]=statistics.median(values)
            entry[metric+"_mib_range"]=[min(values),max(values)]
        summary.append(entry)
axes[0].set_ylabel("Cgroup memory.current (MiB)");axes[0].legend()
fig.suptitle("Cgroup charge and configured soft limit",fontsize=14);fig.tight_layout()
for ext in ["svg","png"]: fig.savefig(charts/f"cgroup-charge.{ext}",dpi=160)
(root/"summary.json").write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
