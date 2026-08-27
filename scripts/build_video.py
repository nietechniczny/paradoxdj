#!/usr/bin/env python3
"""Render the set's video layer from the same plan the audio was built from.

Because it reads the same plan.json, every video transition lands on exactly
the same frame as its audio crossfade -- no drift, no manual alignment.

Each segment is one looping clip, fed in with -stream_loop and trimmed to the
segment length, then chained with xfade. Inputs are the small looped clips from
make_loops.py, so 28 simultaneous decoders stay cheap.
"""
import argparse, json, os, subprocess, sys


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--loops", required=True, help="folder from make_loops.py")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title-card", help="transparent PNG from make_title_card.py")
    ap.add_argument("--title-in", type=float, default=1.5)
    ap.add_argument("--title-hold", type=float, default=10.5)
    ap.add_argument("--title-fade", type=float, default=2.0)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--encoder", default="auto")
    ap.add_argument("--bitrate", default="9M")
    ap.add_argument("--stats", action="store_true",
                    help="stream ffmpeg progress (noisy; useful for long renders)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    P = json.load(open(a.plan))
    plan, X, total = P["plan"], P["xfade"], P["total"]

    loops = sorted(f for f in os.listdir(a.loops) if f.lower().endswith(".mp4"))
    if not loops:
        sys.exit(f"no loops in {a.loops}")

    enc = a.encoder
    if enc == "auto":
        have = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                              capture_output=True, text=True).stdout
        enc = "h264_videotoolbox" if "h264_videotoolbox" in have else "libx264"

    inputs, chosen = [], []
    for i, p in enumerate(plan):
        name = p.get("clip")
        stem = os.path.splitext(name)[0] + ".mp4" if name else None
        clip = stem if stem in loops else loops[i % len(loops)]
        # never repeat a clip back to back
        if chosen and clip == chosen[-1] and len(loops) > 1:
            clip = loops[(loops.index(clip) + 1) % len(loops)]
        chosen.append(clip)
        inputs += ["-stream_loop", "-1", "-t", str(p["seg"]),
                   "-i", os.path.join(a.loops, clip)]

    f = [f"[{i}:v]fps={a.fps},setpts=PTS-STARTPTS,format=yuv420p[v{i}]"
         for i in range(len(plan))]
    cur, cum = "v0", plan[0]["seg"]
    for i in range(1, len(plan)):
        f.append(f"[{cur}][v{i}]xfade=transition=fade:duration={X}:"
                 f"offset={cum - X:.3f}[w{i}]")
        cur = f"w{i}"
        cum += plan[i]["seg"] - X

    if a.title_card:
        hold_end = a.title_in + a.title_fade + a.title_hold
        span = hold_end + a.title_fade + 1
        inputs += ["-loop", "1", "-t", str(span), "-i", a.title_card]
        ti = len(plan)
        f.append(f"[{ti}:v]fps={a.fps},format=rgba,setpts=PTS-STARTPTS,"
                 f"fade=t=in:st={a.title_in}:d={a.title_fade}:alpha=1,"
                 f"fade=t=out:st={hold_end}:d={a.title_fade}:alpha=1[title]")
        f.append(f"[{cur}][title]overlay=0:0:enable='lt(t,{span})':format=auto[ov]")
        cur = "ov"

    f.append(f"[{cur}]fade=t=in:st=0:d=2.5,"
             f"fade=t=out:st={total - 8:.2f}:d=8,format=yuv420p[vout]")

    script = os.path.join(os.path.dirname(os.path.abspath(a.out)) or ".", ".pdj_vfilter.txt")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    open(script, "w").write(";\n".join(f))

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + (["-stats"] if a.stats else []) + inputs + [
        "-filter_complex_script", script, "-map", "[vout]", "-an", "-c:v", enc]
    cmd += (["-b:v", a.bitrate, "-maxrate", a.bitrate, "-bufsize", "18M"]
            if enc == "h264_videotoolbox" else ["-crf", "20", "-preset", "medium"])
    cmd += ["-pix_fmt", "yuv420p", "-movflags", "+faststart", a.out]

    if a.dry_run:
        print(" ".join(cmd))
        return
    print(f"rendering {len(plan)} segments -> {a.out} "
          f"({int(total)//60}:{int(total)%60:02d} at {a.width}x{a.height}/{a.fps}, encoder {enc})")
    r = subprocess.run(cmd)
    os.unlink(script)
    if r.returncode != 0:
        sys.exit(f"ffmpeg failed with code {r.returncode}")
    print("done")


if __name__ == "__main__":
    main()
