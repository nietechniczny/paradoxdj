#!/usr/bin/env python3
"""Render the continuous mix from a plan, using bass-swap crossfades.

A plain crossfade between two dance tracks puts two kick drums and two basslines
on top of each other for the length of the fade. The low end doubles up, the
result is muddy, and any tempo difference is maximally audible down there.

What DJs actually do -- and what this implements -- is a bass swap: the outgoing
track is high-passed for the duration of the transition, so it keeps its melody
and hats but gives up its kick and bass, while the incoming track arrives at
full bandwidth. Only one low end is ever playing.

Signal chain per segment:
    trim -> gain (to a common LUFS) -> [head | high-passed tail] -> crossfade

then, on the finished mix: fade in, fade out, limiter, true-peak trim.
"""
import argparse, json, os, re, subprocess, sys


def build_filter(plan, xfade, hp_hz, makeup_db, tp_trim_db, fade_in, fade_out, total):
    f = []
    n = len(plan)
    for i, p in enumerate(plan):
        seg, gain = p["seg"], p["gain_db"]
        base = (f"[{i}:a]aformat=sample_fmts=fltp:sample_rates=44100:"
                f"channel_layouts=stereo,volume={gain}dB")
        if i == n - 1:
            f.append(base + f"[s{i}]")
            continue
        # split the segment: body untouched, last `xfade` seconds high-passed
        f.append(base + f",asplit=2[h{i}][t{i}]")
        f.append(f"[h{i}]atrim=0:{seg - xfade},asetpts=N/SR/TB[hh{i}]")
        f.append(f"[t{i}]atrim={seg - xfade}:{seg},asetpts=N/SR/TB,"
                 f"highpass=f={hp_hz}:poles=2,highpass=f={hp_hz}:poles=2,"
                 f"volume={makeup_db}dB[tt{i}]")
        f.append(f"[hh{i}][tt{i}]concat=n=2:v=0:a=1[s{i}]")

    cur = "s0"
    for i in range(1, n):
        f.append(f"[{cur}][s{i}]acrossfade=d={xfade}:c1=qsin:c2=qsin[x{i}]")
        cur = f"x{i}"

    f.append(
        f"[{cur}]afade=t=in:st=0:d={fade_in},"
        f"afade=t=out:st={total - fade_out:.2f}:d={fade_out},"
        f"alimiter=level_in=1:level_out=1:limit=0.891:attack=5:release=60,"
        f"volume={tp_trim_db}dB,"
        f"aformat=sample_fmts=s16:sample_rates=44100:channel_layouts=stereo[mix]")
    return ";\n".join(f)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", required=True, help="output .wav (use build_audio then encode)")
    ap.add_argument("--highpass", type=float, default=180.0,
                    help="Hz, bass removed from the outgoing track during the fade")
    ap.add_argument("--makeup", type=float, default=4.0,
                    help="dB added back to the high-passed tail to fill the hole")
    ap.add_argument("--tp-trim", type=float, default=-1.8,
                    help="dB trim after the limiter, for inter-sample peaks")
    ap.add_argument("--fade-in", type=float, default=3.0)
    ap.add_argument("--fade-out", type=float, default=10.0)
    ap.add_argument("--stats", action="store_true",
                    help="stream ffmpeg progress (noisy; useful for long renders)")
    ap.add_argument("--dry-run", action="store_true", help="print the ffmpeg command only")
    a = ap.parse_args()

    P = json.load(open(a.plan))
    plan, X, total = P["plan"], P["xfade"], P["total"]

    inputs = []
    for p in plan:
        inputs += ["-ss", str(p["start"]), "-t", str(p["seg"]), "-i", p["path"]]

    graph = build_filter(plan, X, a.highpass, a.makeup, a.tp_trim,
                         a.fade_in, a.fade_out, total)
    script = os.path.join(os.path.dirname(os.path.abspath(a.out)) or ".", ".pdj_afilter.txt")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(script, "w") as fh:
        fh.write(graph)

    cmd = (["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + (["-stats"] if a.stats else [])
           + inputs
           + ["-filter_complex_script", script, "-map", "[mix]",
              "-map_metadata", "-1", "-c:a", "pcm_s16le", a.out])

    if a.dry_run:
        print(" ".join(cmd))
        return

    print(f"rendering {len(plan)} segments -> {a.out} "
          f"({int(total)//60}:{int(total)%60:02d}, {X:g}s bass-swap crossfades)")
    r = subprocess.run(cmd)
    os.unlink(script)
    if r.returncode != 0:
        sys.exit(f"ffmpeg failed with code {r.returncode}")
    print("done")


if __name__ == "__main__":
    main()
