#!/usr/bin/env python3
"""Mux the final deliverables and emit the YouTube chapter list.

Produces:
  * <name>.mp3        tagged, for local play and distribution
  * <name> 1080p.mp4  video + audio, faststart, ready to upload
  * chapters.txt      timestamps YouTube turns into chapters
"""
import argparse, json, os, subprocess, sys


def fmt(s):
    s = int(round(s))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--mix", required=True, help="mix.wav from build_audio.py")
    ap.add_argument("--video", help="video from build_video.py (omit for audio only)")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--name", required=True, help='e.g. "NORTHBOUND - Matt Paradox"')
    ap.add_argument("--artist", default="")
    ap.add_argument("--album", default="")
    ap.add_argument("--producer", default="")
    ap.add_argument("--genre", default="")
    ap.add_argument("--trim", type=float, default=0.0,
                    help="dB applied on export, e.g. -0.5 for true-peak headroom")
    a = ap.parse_args()

    P = json.load(open(a.plan))
    os.makedirs(a.outdir, exist_ok=True)
    meta = []
    for k, v in (("title", a.name), ("artist", a.artist), ("album_artist", a.artist),
                 ("album", a.album or a.name), ("genre", a.genre),
                 ("comment", f"Produced by {a.producer}" if a.producer else "")):
        if v:
            meta += ["-metadata", f"{k}={v}"]
    af = ["-af", f"volume={a.trim}dB"] if a.trim else []

    mp3 = os.path.join(a.outdir, f"{a.name}.mp3")
    print(f"-> {mp3}")
    if subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                       "-i", a.mix] + af + ["-c:a", "libmp3lame", "-b:a", "320k"]
                      + meta + [mp3]).returncode != 0:
        sys.exit("mp3 export failed")

    if a.video:
        mp4 = os.path.join(a.outdir, f"{a.name} 1080p.mp4")
        print(f"-> {mp4}")
        if subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-stats",
                           "-i", a.video, "-i", a.mix] + af +
                          ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                           "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-shortest"]
                          + meta + ["-movflags", "+faststart", mp4]).returncode != 0:
            sys.exit("mp4 mux failed")

    ch = os.path.join(a.outdir, "chapters.txt")
    with open(ch, "w") as fh:
        for p in P["plan"]:
            fh.write(f"{fmt(p['cue'])} {p['title']}\n")
    print(f"-> {ch}  ({len(P['plan'])} chapters)")
    print("\nFirst chapter must be 0:00 and every chapter at least 10 s long, "
          "or YouTube silently ignores the list.")


if __name__ == "__main__":
    main()
