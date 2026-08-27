#!/usr/bin/env python3
"""Turn analysed tracks into a segment plan that hits a target set length.

Two things this gets right that hand-planning does not:

1. LENGTH IS SOLVED, NOT GUESSED. With N segments and a crossfade of X seconds,
   the finished set is sum(segments) - (N-1)*X. The script solves for segment
   lengths so the result lands on the requested duration.

2. IN-POINTS ARE CHOSEN BY ENERGY, NOT BY A FIXED OFFSET. Starting every track
   at a fixed offset (say 20 s) reliably lands some of them in a sparse verse.
   Because a DJ-style transition strips the bass off the OUTGOING track, an
   incoming track with no energy leaves an audible hole. The score below weights
   the first 10 s (entry punch), the whole segment (overall level) and the last
   10 s (exit punch, so the next transition has something to fade out of).

Output: JSON consumed by build_audio.py and build_video.py.
"""
import argparse, json, os, re, sys
import numpy as np


def parse_time(s):
    """Accept 72:00, 1:12:00 or plain seconds."""
    parts = str(s).split(":")
    if len(parts) == 1:
        return float(parts[0])
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    return total


def clean_title(filename):
    """Drop a leading sort prefix: '07 - Dont Pick Up.mp3' -> 'Dont Pick Up'."""
    stem = os.path.splitext(filename)[0]
    return re.sub(r"^\s*\d{1,3}\s*[-._)]\s*", "", stem).strip() or stem


def fmt(sec):
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


class Curve:
    """Short-term loudness curve with convenience windows."""

    def __init__(self, values, step):
        self.v = np.array(values, dtype=float) if values else np.array([-70.0])
        self.step = step

    def mean(self, a, b):
        i, j = int(a / self.step), int(b / self.step)
        seg = self.v[max(0, i):max(1, j)]
        seg = seg[seg > -60]
        return float(seg.mean()) if seg.size else -99.0

    def min(self, a, b):
        i, j = int(a / self.step), int(b / self.step)
        seg = self.v[max(0, i):max(1, j)]
        seg = seg[seg > -60]
        return float(seg.min()) if seg.size else -99.0

    def low_pct(self, a, b, pct=10):
        """Percentile of the quiet end -- catches a breakdown mid-fragment."""
        i, j = int(a / self.step), int(b / self.step)
        seg = self.v[max(0, i):max(1, j)]
        seg = seg[seg > -60]
        return float(np.percentile(seg, pct)) if seg.size else -99.0


def pick_in_point(curve, duration, seg, edge=10.0, guard=2.0, step=0.5,
                  max_frac=0.6):
    """Best start offset: punchy entry, solid body, punchy exit.

    `edge` must match the crossfade length. Scoring a 10 s entry window when the
    transition actually runs 16 s judges the wrong audio: the second half of the
    blend is the part that was never looked at, and that is where holes appear.
    """
    lo = min(8.0, max(0.0, duration - seg - guard))
    hi = max(lo, min(max_frac * duration, duration - seg - guard))
    best, best_score = lo, -1e9
    s = lo
    while s <= hi:
        score = (0.30 * curve.mean(s, s + edge)          # enters with punch
                 + 0.10 * curve.mean(s, s + seg)          # overall level
                 + 0.25 * curve.mean(s + seg - edge, s + seg)   # exits with punch
                 + 0.10 * curve.min(s + seg - edge, s + seg)    # no hole at the hand-off
                 + 0.25 * curve.low_pct(s, s + seg))      # no deep breakdown inside
        if score > best_score:
            best, best_score = s, score
        s += step
    return round(best, 2)


DEFAULT_SHAPE = [
    # (label, share of the set, relative segment weight)
    ("warm-up",   0.14, 0.85),
    ("build",     0.20, 0.95),
    ("rise",      0.16, 1.00),
    ("peak-a",    0.14, 1.10),
    ("bridge",    0.08, 1.10),
    ("peak-b",    0.16, 1.20),
    ("descent",   0.06, 1.10),
    ("outro",     0.06, 0.95),
]


def assign_phases(n, shape):
    """Map n slots onto the energy arc.

    Each slot takes the position (i+0.5)/n along the set and lands in whichever
    phase spans it. Short sets therefore keep the SHAPE of the arc -- warm-up
    first, peak in the middle, outro last -- instead of losing whole phases off
    one end, which is what happens if you round per-phase track counts.
    """
    shares = np.array([s[1] for s in shape], dtype=float)
    edges = np.concatenate([[0.0], np.cumsum(shares / shares.sum())])
    out = []
    for i in range(n):
        pos = (i + 0.5) / n
        j = int(np.searchsorted(edges, pos, side="right") - 1)
        j = min(max(j, 0), len(shape) - 1)
        out.append((shape[j][0], shape[j][2]))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tracks", required=True, help="tracks.json from analyze_tracks.py")
    ap.add_argument("--target", required=True, help="target set length, e.g. 60:00")
    ap.add_argument("--xfade", type=float, default=8.0, help="crossfade seconds")
    ap.add_argument("--out", required=True, help="plan.json to write")
    ap.add_argument("--order", help="file with one track filename per line (set order)")
    ap.add_argument("--exclude-class", default="",
                    help="drop tracks with these grid classes, e.g. C")
    ap.add_argument("--clips", help="folder of looping video clips to assign")
    ap.add_argument("--target-lufs", type=float, default=-11.0,
                    help="per-segment loudness target before the master limiter")
    ap.add_argument("--target-bpm", default=None,
                    help="'auto' (median of the tracks) or a number. Enables tempo "
                         "lock and bar quantisation: every track is time-stretched to "
                         "this tempo and segments become whole bars.")
    ap.add_argument("--crossfade-bars", type=int, default=8,
                    help="transition length in bars when --target-bpm is set")
    ap.add_argument("--max-stretch", type=float, default=6.0,
                    help="percent; tracks needing more than this are dropped from a "
                         "tempo-locked set rather than audibly mangled")
    a = ap.parse_args()

    data = json.load(open(a.tracks))
    tracks = data["tracks"]

    if a.exclude_class:
        drop = set(a.exclude_class.split(","))
        kept = [t for t in tracks if t.get("grid_class") not in drop]
        print(f"excluded {len(tracks) - len(kept)} track(s) by grid class {sorted(drop)}")
        tracks = kept

    if a.order:
        want = [l.strip() for l in open(a.order) if l.strip()]
        by_name = {t["file"]: t for t in tracks}
        missing = [w for w in want if w not in by_name]
        if missing:
            sys.exit("order file lists tracks not present: " + ", ".join(missing))
        tracks = [by_name[w] for w in want]

    n = len(tracks)
    if n < 2:
        sys.exit("need at least 2 tracks")
    target = parse_time(a.target)
    X = a.xfade

    # --- tempo lock -------------------------------------------------------
    # Beatmatching means every track playing at ONE tempo. Stretch each to the
    # target with rubberband (build_audio does the work; here we only decide
    # the ratios) and refuse tracks that would need an audible amount of it.
    target_bpm = None
    bar = None
    if a.target_bpm:
        bpms = [(t.get("grid") or {}).get("bpm") for t in tracks]
        if any(b is None for b in bpms):
            sys.exit("--target-bpm needs beat-grid data; re-run analyze_tracks without --no-grid")
        target_bpm = (float(np.median(bpms)) if a.target_bpm == "auto"
                      else float(a.target_bpm))
        keep = []
        for t, b in zip(tracks, bpms):
            pct = abs(target_bpm / b - 1.0) * 100
            if pct > a.max_stretch:
                print(f"dropping {t['file']}: {b:.2f} BPM needs {pct:.1f}% stretch "
                      f"(limit {a.max_stretch}%)")
            else:
                keep.append(t)
        tracks = keep
        n = len(tracks)
        if n < 2:
            sys.exit("too few tracks survive the stretch limit; raise --max-stretch "
                     "or pick a target closer to the material")
        bar = 4 * 60.0 / target_bpm
        X = a.crossfade_bars * bar
        print(f"tempo lock: {target_bpm:.2f} BPM, bar {bar:.3f}s, "
              f"crossfade {a.crossfade_bars} bars ({X:.2f}s), {n} tracks")

    # sum(segments) = target + (n-1)*X, distributed by phase weight
    phases = assign_phases(n, DEFAULT_SHAPE)
    rel = np.array([p[1] for p in phases], dtype=float)
    total_needed = target + (n - 1) * X
    segs = rel / rel.sum() * total_needed

    # clamp to what each file can actually provide, then redistribute the slack
    guard = 2.0
    caps = np.array([t["duration"] - guard for t in tracks])
    segs = np.minimum(segs, caps)
    for _ in range(50):
        deficit = total_needed - segs.sum()
        if abs(deficit) < 0.5:
            break
        room = caps - segs
        if deficit > 0 and room.sum() > 0:
            segs += room / room.sum() * deficit
            segs = np.minimum(segs, caps)
        else:
            segs += deficit / n
    segs = np.maximum(segs, X + 20.0)

    if target_bpm:
        # Round each segment to whole bars, then fix the rounding remainder on
        # the segments with the most room, so the total stays on target.
        ratios = np.array([target_bpm / (t["grid"]["bpm"]) for t in tracks])
        cap_bars = np.floor((caps / ratios) / bar).astype(int)
        want = int(round((target + (n - 1) * X) / bar))
        bars = np.maximum(4, np.round(segs / bar).astype(int))
        bars = np.minimum(bars, cap_bars)
        for _ in range(2000):
            diff = want - int(bars.sum())
            if diff == 0:
                break
            if diff > 0:
                room = cap_bars - bars
                if room.max() <= 0:
                    print(f"note: {diff} bars short of target; material is too short")
                    break
                bars[int(np.argmax(room))] += 1
            else:
                idx = int(np.argmax(bars))
                if bars[idx] <= 4:
                    break
                bars[idx] -= 1
        segs = bars * bar

    clips = []
    if a.clips:
        clips = sorted(f for f in os.listdir(a.clips)
                       if f.lower().endswith((".mp4", ".mov", ".webm")))
        if not clips:
            sys.exit(f"no video clips in {a.clips}")

    plan, cue = [], 0.0
    for i, (t, (label, _), seg) in enumerate(zip(tracks, phases, segs)):
        seg = float(round(seg, 2))
        curve = Curve(t.get("curve"), t.get("curve_step", 0.5))
        g = t.get("grid") or {}
        ratio = target_bpm / g["bpm"] if target_bpm else 1.0
        src_len = seg * ratio                      # seconds taken from the source
        # score the same span the crossfade will actually use
        edge = max(8.0, min(X * ratio, src_len / 3))
        start = pick_in_point(curve, t["duration"], src_len, edge=edge)
        if target_bpm:
            # snap to a downbeat so bars line up once the tempo matches
            src_bar = g["bar_seconds"]
            k = round((start - g["downbeat"]) / src_bar)
            snapped = g["downbeat"] + k * src_bar
            if snapped < 0:
                snapped += src_bar
            if snapped + src_len <= t["duration"] - 0.5:
                start = round(snapped, 4)
        gain = round(a.target_lufs - t["lufs"], 2) if t.get("lufs") else 0.0
        item = dict(index=i + 1, file=t["file"], path=t["path"],
                    title=clean_title(t["file"]),
                    phase=label, start=start, seg=round(seg, 4), cue=round(cue, 4),
                    gain_db=gain, grid_class=t.get("grid_class"),
                    bpm=(t.get("grid") or {}).get("bpm"),
                    stretch=round(ratio, 6), src_seconds=round(src_len, 4),
                    bars=int(round(seg / bar)) if target_bpm else None)
        if clips:
            # avoid repeating a clip back-to-back
            item["clip"] = clips[i % len(clips)] if len(clips) > 1 else clips[0]
            item["clip_path"] = os.path.abspath(os.path.join(a.clips, item["clip"]))
        plan.append(item)
        cue += seg - X

    total = cue + X
    out = dict(target=target, xfade=round(X, 4), total=round(total, 2),
               target_bpm=target_bpm, bar_seconds=bar,
               crossfade_bars=(a.crossfade_bars if target_bpm else None),
               target_lufs=a.target_lufs, clips_dir=os.path.abspath(a.clips) if a.clips else None,
               plan=plan)
    json.dump(out, open(a.out, "w"), indent=1)

    hdr = f"\n{'cue':>7} {'#':>3}  {'track':<30} {'phase':<9} {'seg':>6} {'in':>7} {'gain':>6} {'bpm':>7}"
    if target_bpm:
        hdr += f" {'bars':>5} {'stretch':>8}"
    print(hdr)
    for p in plan:
        line = (f"{fmt(p['cue']):>7} {p['index']:>3}  {p['title'][:30]:<30} {p['phase']:<9} "
                f"{fmt(p['seg']):>6} {fmt(p['start']):>7} {p['gain_db']:>+6.1f} "
                f"{(p['bpm'] or 0):>7.2f}")
        if target_bpm:
            line += f" {p['bars']:>5} {(p['stretch'] - 1) * 100:>+7.2f}%"
        print(line)
    print(f"\ntarget {fmt(target)} -> planned {fmt(total)} "
          f"({n} segments, {a.xfade:g}s crossfades)  wrote {a.out}")


if __name__ == "__main__":
    main()
