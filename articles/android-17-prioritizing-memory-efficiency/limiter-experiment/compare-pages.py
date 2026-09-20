"""Reproducible, bounded Pixel page-type comparison; no root or global overrides."""
import argparse, csv, datetime, hashlib, json, pathlib, random, signal, subprocess, time
PKG = "com.returnzero.limiter"
FIELDS = ["seconds", "VmRSS", "RssAnon", "RssFile", "RssShmem", "VmSwap", "current", "swap_current", "high", "swap_max", "high_events"]
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--device", required=True)
    p.add_argument("--iterations", type=int, default=5)
    p.add_argument("--duration", type=int, default=30)
    a = p.parse_args()
    if not 1 <= a.iterations <= 5 or not 25 <= a.duration <= 60: p.error("Use 1-5 trials and 25-60 seconds")
    root = pathlib.Path(__file__).parent / "results" / datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root.mkdir(parents=True)
    active = root
    def adb(*args, optional=False):
        r = subprocess.run(["adb", "-s", a.device, *args], capture_output=True, text=True, timeout=15)
        with (active / "raw.jsonl").open("a") as f:
            f.write(json.dumps(dict(time=time.time(), command=args, stdout=r.stdout, stderr=r.stderr, code=r.returncode))+"\n")
        if r.returncode and not optional: raise RuntimeError(r.stderr or r.stdout)
        return r.stdout.strip()
    def shell(*args, **kw): return adb("shell", *args, **kw)
    def alive(name): return shell("pidof", name, optional=True)
    def stop(*_): raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, stop)
    status = shell("am", "memory-limiter", "status")
    if "enabled" not in status or "ignored=none" not in status: raise RuntimeError("Limiter inactive or existing ignore settings")
    meta = dict(build=shell("getprop","ro.build.fingerprint"), sdk=shell("getprop","ro.build.version.sdk"),
                status=status, help=shell("am","help"), meminfo=shell("cat","/proc/meminfo"), battery=shell("dumpsys","battery"),
                seed=17037, limit_mib=128, workload_mib=256, duration=a.duration, iterations=a.iterations,
                protocol="One page touched per allocation page; anonymous pages highly compressible. Warm file cache, fsynced before trials.")
    (root/"metadata.json").write_text(json.dumps(meta,indent=2))
    def launch():
        shell("am","force-stop",PKG)
        shell("am","start","-n",PKG+"/.MainActivity")
        for _ in range(30):
            pid = alive(PKG+":heavy")
            if pid.isdigit(): return pid
            time.sleep(.5)
        raise RuntimeError("Worker not ready; unlock device and inspect app")
    pid = launch()
    try:
        shell("am","startservice","-n",PKG+"/.HeavyService","--ez","prepare","true")
        for _ in range(60):
            logs = shell("logcat","-d","--pid="+pid,"-s","LimiterExp:I")
            if "prepared bytes=268435456" in logs: break
            time.sleep(.5)
        else: raise RuntimeError("File preparation incomplete")
    finally: shell("am","force-stop",PKG)
    trials=[]
    order=["anon","file","dirty"]*a.iterations
    random.Random(17037).shuffle(order)
    for index, mode in enumerate(order):
        active=root/f"{index+1:02d}-{mode}"
        active.mkdir()
        pid=None
        result=dict(mode=mode, trial=index+1, outcome="incomplete")
        try:
            battery=shell("dumpsys","battery")
            temp=int(next(l.split(":")[1] for l in battery.splitlines() if l.strip().startswith("temperature:")))
            if temp>=380: raise RuntimeError("Battery temperature >=38C; trial stopped")
            pid=launch()
            mainpid=alive(PKG)
            cg=shell("cat","/proc/"+pid+"/cgroup").split("0::")[-1].strip()
            base="/sys/fs/cgroup"+cg+"/"
            def read(name): return shell("cat",base+name)
            result["before"]={n:read(n) for n in ["memory.high","memory.swap.high","memory.swap.max","memory.max"]}
            shell("am","memory-limiter","manual",pid,"128")
            result["limited"]={n:read(n) for n in result["before"]}
            if result["limited"]["memory.high"]!="134217728": raise RuntimeError("Manual units mismatch")
            shell("dumpsys","meminfo",pid)
            shell("cat","/proc/meminfo")
            start=time.monotonic()
            def sample():
                raw=shell("cat","/proc/"+pid+"/status")
                row={"seconds":time.monotonic()-start}
                for line in raw.splitlines():
                    k,_,v=line.partition(":")
                    if k in FIELDS: row[k]=int(v.split()[0])
                for col,name in [("current","memory.current"),("swap_current","memory.swap.current"),("high","memory.high"),("swap_max","memory.swap.max")]:
                    val=read(name);row[col]=int(val) if val!="max" else val
                events=dict(line.split() for line in read("memory.events").splitlines())
                row["high_events"]=int(events["high"])
                return row
            with (active/"samples.csv").open("w") as f:
                writer=csv.DictWriter(f,fieldnames=FIELDS); writer.writeheader()
                writer.writerow(sample());f.flush()
                shell("am","startservice","-n",PKG+"/.HeavyService","--ei","mode",str(["anon","file","dirty"].index(mode)),"--ei","total_mb","256")
                while time.monotonic()-start<a.duration:
                    if alive(PKG+":heavy")!=pid: break
                    writer.writerow(sample());f.flush();time.sleep(.5)
            result["worker_survived"]=alive(PKG+":heavy")==pid
            result["main_survived"]=alive(PKG)==mainpid
            result["allocation_log"]=shell("logcat","-d","--pid="+pid,"-s","LimiterExp:I")
            result["allocation_complete"]="allocated_mb=256 ok=true" in result["allocation_log"]
            result["exit_info"]=shell("dumpsys","activity","exit-info",PKG)
            if result["worker_survived"]:
                shell("dumpsys","meminfo",pid)
                shell("cat","/proc/"+pid+"/smaps",optional=True)
                result["after"]={n:read(n) for n in result["before"]}
            if not result["allocation_complete"] and result["worker_survived"]: raise RuntimeError("Workload incomplete")
            result["outcome"]="completed"
        finally:
            try:
                if pid and alive(PKG+":heavy")==pid: shell("am","memory-limiter","manual",pid,"none")
            finally:
                shell("am","force-stop",PKG)
                (active/"result.json").write_text(json.dumps(result,indent=2))
        trials.append(result)
        print(f"{index+1}/{len(order)} {mode}: survived={result['worker_survived']} allocation_complete={result['allocation_complete']}",flush=True)
    active=root
    meta["final_status"]=shell("am","memory-limiter","status")
    meta["final_battery"]=shell("dumpsys","battery")
    (root/"metadata.json").write_text(json.dumps(meta,indent=2))
    print(root,flush=True)
if __name__=="__main__": main()
