#!/usr/bin/env python3
"""Quality-control a rendered mix. Fails loudly instead of shipping a bad file.

Checks:
  * integrated loudness and true peak against publishing limits
  * loudness at every transition -- catches the hole a bad in-point leaves
  * silences long enough to sound like a dropout

Exit code 1 if any hard check fails, so it can gate a build.
"""
import argparse, json, re, subprocess, sys
import numpy as np


def fmt(s):
    s = int(s)
    return f"{s // 60}:{s % 60:02d}"


def st_curve(path):
    tmp = "/tmp/_pdj_verify.txt"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", path,
                    "-af", f"ebur128=metadata=1,ametadata=mode=print:key=lavfi.r128.S:file={tmp}",
                    "-f", "null", "-"], check=True)
    times, vals, t = [], [], None
    for line in open(tmp):
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            t = float(m.group(1))
            continue
        m = re.search(r"lavfi\.r128\.S=(-?[\d.]+)", line)
        if m and t is not None:
            times.append(t)
            vals.append(float(m.group(1)))
    return np.array(times), np.array(vals)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mix", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--max-dip", type=float, default=4.0,
                    help="LU: how far a transition may fall below the preceding level")
    ap.add_argument("--max-true-peak", type=float, default=-1.0, help="dBFS")
    ap.add_argument("--target-lufs", type=float, default=-12.0)
    ap.add_argument("--lufs-tolerance", type=float, default=1.5)
    a = ap.parse_args()

    P = json.load(open(a.plan))
    plan, X = P["plan"], P["xfade"]

    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", a.mix,
                          "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr[-2500:]
    I = float(re.search(r"I:\s*(-?\d+\.?\d*)\s*LUFS", err).group(1))
    LRA = float(re.search(r"LRA:\s*(-?\d+\.?\d*)\s*LU", err).group(1))
    TP = float(re.search(r"Peak:\s*(-?\d+\.?\d*)\s*dBFS", err).group(1))

    fails = []
    print(f"integrated  {I:>7.1f} LUFS   (target {a.target_lufs:+.1f} +/- {a.lufs_tolerance})")
    print(f"range       {LRA:>7.1f} LU")
    print(f"true peak   {TP:>7.1f} dBFS   (limit {a.max_true_peak:+.1f})")
    if TP > a.max_true_peak:
        fails.append(f"true peak {TP:+.1f} dBFS exceeds {a.max_true_peak:+.1f}")
    if abs(I - a.target_lufs) > a.lufs_tolerance:
        fails.append(f"integrated {I:+.1f} LUFS off target {a.target_lufs:+.1f}")

    t, v = st_curve(a.mix)
    print(f"\n{'cue':>7}  transition                              dip")
    bad = 0
    for i in range(1, len(plan)):
        c = plan[i]["cue"]
        win = v[(t >= c - 1) & (t <= c + X + 1)]
        ref = v[(t >= c - 30) & (t <= c - 12)]
        win, ref = win[win > -60], ref[ref > -60]
        if not win.size or not ref.size:
            continue
        dip = win.min() - ref.mean()
        flag = ""
        if dip < -a.max_dip:
            bad += 1
            flag = "  <-- HOLE"
        name = f"{plan[i-1]['title'][:16]} -> {plan[i]['title'][:16]}"
        print(f"{fmt(c):>7}  {name:<40} {dip:+5.1f} LU{flag}")
    if bad:
        fails.append(f"{bad} transition(s) drop more than {a.max_dip} LU")

    quiet = t[(v < -40) & (t > 10) & (t < t[-1] - 20)]
    if quiet.size:
        groups, cur = [], [quiet[0]]
        for x in quiet[1:]:
            if x - cur[-1] < 1.0:
                cur.append(x)
            else:
                groups.append(cur)
                cur = [x]
        groups.append(cur)
        long = [g for g in groups if g[-1] - g[0] > 3.0]
        if long:
            print("\nnear-silences longer than 3 s (check these are intended breakdowns):")
            for g in long:
                print(f"  {fmt(g[0])} - {fmt(g[-1])}  ({g[-1]-g[0]:.1f} s)")

    print()
    if fails:
        for f in fails:
            print(f"FAIL: {f}")
        sys.exit(1)
    print(f"PASS - {len(plan)} segments, {len(plan)-1} transitions, "
          f"{bad} over the {a.max_dip} LU dip limit")


if __name__ == "__main__":
    main()
