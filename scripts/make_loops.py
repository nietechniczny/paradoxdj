#!/usr/bin/env python3
"""Turn generated clips into seamless, correctly framed loops.

Two problems with raw generated clips:

  * They do not loop. The last frame rarely matches the first, so repeating one
    produces a visible jump. Fixed here by crossfading the clip's final second
    into its first second and dropping that second from the end -- the result
    is one second shorter and joins to itself invisibly.

  * They are the wrong shape. A 9:16 clip in a 16:9 set has to be cropped;
    centre-cropping the widest 16:9 region out of it keeps the subject and
    avoids pillarboxing.
"""
import argparse, os, subprocess, sys


def duration(path):
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip())


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="indir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--blend", type=float, default=1.0,
                    help="seconds of loop-joint crossfade")
    ap.add_argument("--encoder", default="auto",
                    help="h264_videotoolbox (macOS), libx264, or auto")
    ap.add_argument("--bitrate", default="12M")
    a = ap.parse_args()

    enc = a.encoder
    if enc == "auto":
        have = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                              capture_output=True, text=True).stdout
        enc = "h264_videotoolbox" if "h264_videotoolbox" in have else "libx264"
        print(f"encoder: {enc}")

    os.makedirs(a.out, exist_ok=True)
    files = sorted(f for f in os.listdir(a.indir)
                   if f.lower().endswith((".mp4", ".mov", ".webm")))
    if not files:
        sys.exit(f"no clips in {a.indir}")

    ar = a.width / a.height
    for f in files:
        src = os.path.join(a.indir, f)
        dst = os.path.join(a.out, os.path.splitext(f)[0] + ".mp4")
        L = duration(src)
        if L <= a.blend * 2 + 0.5:
            print(f"{f}: too short ({L:.1f}s) for a {a.blend}s blend, skipping")
            continue
        b = a.blend
        graph = (
            f"[0:v]crop='min(iw,ih*{ar})':'min(iw,ih*{ar})/{ar}',"
            f"scale={a.width}:{a.height},fps={a.fps},format=yuv420p,split=3[p][q][r];"
            f"[p]trim=0:{b},setpts=PTS-STARTPTS[head];"
            f"[q]trim={L-b:.3f}:{L},setpts=PTS-STARTPTS[tail];"
            f"[tail][head]xfade=transition=fade:duration={b}:offset=0[joint];"
            f"[r]trim={b}:{L-b:.3f},setpts=PTS-STARTPTS[body];"
            f"[joint][body]concat=n=2:v=1:a=0[v]"
        )
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src,
               "-filter_complex", graph, "-map", "[v]", "-an", "-c:v", enc]
        cmd += ["-b:v", a.bitrate] if enc == "h264_videotoolbox" else ["-crf", "18", "-preset", "medium"]
        cmd += [dst]
        if subprocess.run(cmd).returncode != 0:
            sys.exit(f"failed on {f}")
        print(f"{f:<40} {L:5.1f}s -> {duration(dst):5.1f}s  {a.width}x{a.height}")
    print(f"\nloops in {a.out}")


if __name__ == "__main__":
    main()
