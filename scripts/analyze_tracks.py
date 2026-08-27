#!/usr/bin/env python3
"""Analyse a folder of audio tracks for DJ-set assembly.

Measures, per track: duration, integrated loudness, true peak, a short-term
loudness curve (used later to pick in-points), and beat-grid stability.

The beat-grid part answers one question: does a CONSTANT tempo grid fit this
file? Generative models (Suno, Udio) often render without a sequencer clock, so
tempo wanders. A track whose grid does not fit cannot be beatmatched by any DJ
software either -- there is nothing stable to lock onto.

Output: JSON consumed by plan_set.py.
"""
import argparse, json, os, re, subprocess, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdj_dsp

SR = 22050
HOP = 512


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def probe_duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "csv=p=0", path]).stdout.strip()
    return float(out)


def loudness(path, start=None, dur=None):
    """Integrated LUFS and true peak for a file or a slice of it."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats"]
    if start is not None:
        cmd += ["-ss", str(start)]
    if dur is not None:
        cmd += ["-t", str(dur)]
    cmd += ["-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"]
    err = run(cmd).stderr[-2000:]
    i = re.search(r"I:\s*(-?\d+\.?\d*)\s*LUFS", err)
    p = re.search(r"Peak:\s*(-?\d+\.?\d*)\s*dBFS", err)
    return (float(i.group(1)) if i else None,
            float(p.group(1)) if p else None)


def short_term_curve(path, step=0.5):
    """Short-term LUFS sampled every `step` seconds. Drives in-point picking."""
    tmp = "/tmp/_pdj_st.txt"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", path,
         "-af", f"ebur128=metadata=1,ametadata=mode=print:key=lavfi.r128.S:file={tmp}",
         "-f", "null", "-"])
    times, vals, t = [], [], None
    with open(tmp) as fh:
        for line in fh:
            m = re.search(r"pts_time:([\d.]+)", line)
            if m:
                t = float(m.group(1))
                continue
            m = re.search(r"lavfi\.r128\.S=(-?[\d.]+)", line)
            if m and t is not None:
                times.append(t)
                vals.append(float(m.group(1)))
    if not times:
        return [], []
    times = np.array(times)
    vals = np.array(vals)
    grid = np.arange(0, times[-1], step)
    return grid.tolist(), np.interp(grid, times, vals).tolist()


def comb_score(onset, bpm, fps):
    """Mean onset strength sampled on a click train at `bpm`, best phase."""
    period = fps * 60.0 / bpm
    n = len(onset)
    best = 0.0
    for off in np.arange(0, period, 0.2):
        g = np.arange(off, n - 1, period)
        i = g.astype(int)
        frac = g - i
        s = ((1 - frac) * onset[i] + frac * onset[i + 1]).mean()
        best = max(best, s)
    return best


def precise_tempo(onset, seed, fps, lo=100.0, hi=160.0):
    """Refine a seed tempo without the bin quantisation librosa's tempo() has."""
    cands = [seed * m for m in (0.5, 2 / 3, 1.0, 1.5, 2.0)]
    cands = [c for c in cands if lo <= c <= hi]
    best = (seed, -1.0)
    for c in cands:
        for bpm in np.arange(max(lo, c - 4), min(hi, c + 4), 0.05):
            s = comb_score(onset, bpm, fps)
            if s > best[1]:
                best = (bpm, s)
    for bpm in np.arange(best[0] - 0.1, best[0] + 0.1, 0.005):
        s = comb_score(onset, bpm, fps)
        if s > best[1]:
            best = (bpm, s)
    return best


def grid_fit(path, seed_bpm):
    """Fit t_i = anchor + i*period to detected beats. Returns fit quality."""
    try:
        import librosa
    except ImportError:
        return None
    y, _ = librosa.load(path, sr=SR, mono=True)
    onset = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP,
                                         aggregate=np.median)
    onset = onset / (onset.max() + 1e-12)
    fps = SR / HOP
    seed = float(np.atleast_1d(librosa.feature.tempo(
        onset_envelope=onset, sr=SR, hop_length=HOP,
        start_bpm=seed_bpm or 128))[0])
    bpm, strength = precise_tempo(onset, seed, fps)
    _, beats = librosa.beat.beat_track(onset_envelope=onset, sr=SR,
                                       hop_length=HOP, bpm=bpm,
                                       tightness=400, units="time", trim=False)
    b = np.asarray(beats)
    if len(b) < 40:
        return None
    ibi = np.diff(b)
    med = np.median(ibi)
    # index each beat, allowing for beats the tracker skipped
    steps = np.maximum(1, np.round(ibi / med)).astype(int)
    idx = np.concatenate([[0], np.cumsum(steps)])
    keep = np.ones(len(b), bool)
    sol = None
    for _ in range(3):
        A = np.vstack([np.ones(keep.sum()), idx[keep]]).T
        sol, *_ = np.linalg.lstsq(A, b[keep], rcond=None)
        res = b - (sol[0] + sol[1] * idx)
        s = res[keep].std()
        keep = np.abs(res) < max(2.5 * s, 0.015)
    fit_bpm = 60 / sol[1]
    rms_ms = float(res[keep].std() * 1000)

    def half(mask):
        A = np.vstack([np.ones(mask.sum()), idx[mask]]).T
        s2, *_ = np.linalg.lstsq(A, b[mask], rcond=None)
        return 60 / s2[1]

    h = len(b) // 2
    m1, m2 = keep.copy(), keep.copy()
    m1[h:] = False
    m2[:h] = False
    drift = (abs(half(m1) - half(m2)) / fit_bpm * 100
             if m1.sum() > 10 and m2.sum() > 10 else float("nan"))
    # Lock the grid to the kick, then find which beat starts the bar. A beat
    # tracker locks onto whatever is most periodic -- frequently the hi-hat or
    # the offbeat -- so its phase is not the one a listener feels.
    mono = pdj_dsp.decode(path, sr=pdj_dsp.SR, mono=True)
    kenv, kfps = pdj_dsp.kick_envelope(mono, pdj_dsp.SR)
    kick_phase, kick_score = pdj_dsp.grid_phase(kenv, kfps, fit_bpm)
    db, db_score = pdj_dsp.downbeat_offset(mono, pdj_dsp.SR, fit_bpm, kick_phase)
    beat = 60.0 / fit_bpm
    return dict(bpm=float(fit_bpm), anchor=float(sol[0]), period=float(sol[1]),
                rms_ms=rms_ms, drift_pct=float(drift), pulse_contrast=float(strength),
                kick_phase=float(kick_phase), kick_contrast=float(kick_score),
                downbeat_beat=int(db),
                downbeat=float(kick_phase + db * beat),
                bar_seconds=float(beat * 4))


def classify(g):
    """A = metronomic, B = warpable, C = no stable grid."""
    if g is None:
        return "?"
    if g["rms_ms"] < 25 and g["drift_pct"] < 0.4:
        return "A"
    if g["drift_pct"] < 1.0:
        return "B"
    return "C"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="indir", required=True, help="folder with audio files")
    ap.add_argument("--out", required=True, help="tracks.json to write")
    ap.add_argument("--ext", default=".mp3,.wav,.flac,.m4a")
    ap.add_argument("--seed-bpm", type=float, default=None,
                    help="hint for tempo search (the BPM you asked the generator for)")
    ap.add_argument("--no-grid", action="store_true",
                    help="skip beat-grid analysis (much faster)")
    a = ap.parse_args()

    exts = tuple(a.ext.split(","))
    files = sorted(f for f in os.listdir(a.indir) if f.lower().endswith(exts))
    if not files:
        sys.exit(f"no audio files in {a.indir}")

    tracks = []
    for f in files:
        path = os.path.join(a.indir, f)
        dur = probe_duration(path)
        lufs, peak = loudness(path)
        t, curve = short_term_curve(path)
        g = None if a.no_grid else grid_fit(path, a.seed_bpm)
        rec = dict(file=f, path=os.path.abspath(path), duration=round(dur, 3),
                   lufs=lufs, true_peak=peak, curve_step=0.5, curve=[round(v, 2) for v in curve],
                   grid=g, grid_class=classify(g))
        tracks.append(rec)
        gs = ("grid %.2f BPM rms %.0fms drift %.2f%% [%s] kick@%.3fs bar %.3fs"
              % (g["bpm"], g["rms_ms"], g["drift_pct"], rec["grid_class"],
                 g["downbeat"], g["bar_seconds"])) if g else "grid: skipped"
        print(f"{f:<40} {dur/60:5.2f} min  {lufs:6.1f} LUFS  {gs}")

    with open(a.out, "w") as fh:
        json.dump(dict(source=os.path.abspath(a.indir), tracks=tracks), fh, indent=1)
    cls = {}
    for t in tracks:
        cls[t["grid_class"]] = cls.get(t["grid_class"], 0) + 1
    print(f"\nwrote {a.out}  ({len(tracks)} tracks)  grid classes: {cls}")


if __name__ == "__main__":
    main()
