#!/usr/bin/env python3
"""Render the continuous mix from a plan.

Two things happen here that ffmpeg cannot do on its own.

TEMPO LOCK. If the plan carries a target BPM, every segment is time-stretched
to it with rubberband before mixing. That is what beatmatching actually is:
one tempo for the whole set, so the kicks of two overlapping tracks land
together instead of flamming.

ADAPTIVE BASS SWAP. A plain crossfade stacks two kicks and two basslines; a
static high-pass on the outgoing track fixes that but leaves a hole whenever
the outgoing track has a breakdown mid-transition. Here the low band is handed
over by a weight computed per bar from the bass power of BOTH tracks, so the
low end is always carried by whichever track actually has one. The bands are
split with a linear-phase FFT crossover that recombines exactly.

Mixing is done in numpy and streamed to ffmpeg, which applies the master chain.
"""
import argparse, json, os, shutil, subprocess, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdj_dsp
from pdj_dsp import SR


def prepare_segment(p, tmpdir, use_rubberband, quiet=True):
    """Extract, gain and (optionally) time-stretch one segment."""
    src_len = p.get("src_seconds") or p["seg"]
    raw = os.path.join(tmpdir, f"seg{p['index']:03d}.wav")
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", str(p["start"]), "-t", str(src_len),
           "-i", p["path"], "-af", f"volume={p['gain_db']}dB",
           "-ac", "2", "-ar", str(SR), "-c:a", "pcm_f32le", raw]
    if subprocess.run(cmd).returncode != 0:
        sys.exit(f"extract failed for {p['file']}")

    ratio = p.get("stretch") or 1.0
    if use_rubberband and abs(ratio - 1.0) > 1e-4:
        out = os.path.join(tmpdir, f"seg{p['index']:03d}_rb.wav")
        rb = ["rubberband", "--tempo", f"{ratio:.6f}", "--fine", raw, out]
        r = subprocess.run(rb, capture_output=quiet)
        if r.returncode != 0:
            sys.exit(f"rubberband failed for {p['file']}: "
                     f"{(r.stderr or b'').decode()[:300]}")
        os.unlink(raw)
        raw = out

    x = pdj_dsp.decode(raw, sr=SR)
    os.unlink(raw)
    want = int(round(p["seg"] * SR))
    if len(x) < want:                      # rubberband can land a hair short
        x = np.vstack([x, np.zeros((want - len(x), 2), dtype=x.dtype)])
    return x[:want].astype(np.float64)


def crossfade(a, b, bar_seconds, hp, adaptive):
    """Blend the tail of `a` into the head of `b`. Equal lengths."""
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    wa, wb = pdj_dsp.equal_power(n)
    if not adaptive:
        return a * wa[:, None] + b * wb[:, None]

    a_lo, a_hi = pdj_dsp.fft_split(a, SR, hp)
    b_lo, b_hi = pdj_dsp.fft_split(b, SR, hp)
    high = a_hi * wa[:, None] + b_hi * wb[:, None]

    n_bars = max(1, int(round(n / (bar_seconds * SR))))
    pa = pdj_dsp.bar_power(a_lo, SR, bar_seconds, n_bars)
    pb = pdj_dsp.bar_power(b_lo, SR, bar_seconds, n_bars)
    base = (np.arange(n_bars) + 0.5) / n_bars
    w = pdj_dsp.smooth_ramp(pdj_dsp.adaptive_bass_weight(pa, pb, base), n)
    norm = pdj_dsp.power_norm(w)
    low = (a_lo * (1 - w)[:, None] + b_lo * w[:, None]) * norm[:, None]
    return low + high


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", required=True, help="output .wav")
    ap.add_argument("--highpass", type=float, default=180.0,
                    help="Hz, crossover between the swapped low band and the rest")
    ap.add_argument("--no-adaptive", action="store_true",
                    help="plain equal-power crossfade, no bass handover")
    ap.add_argument("--no-tempo-lock", action="store_true",
                    help="ignore the plan's target BPM and do not time-stretch")
    ap.add_argument("--target-lufs", type=float, default=-12.0,
                    help="integrated loudness of the finished mix; measured on the "
                         "raw mix and corrected, so crossfade coverage cannot drag it off")
    ap.add_argument("--tp-trim", type=float, default=-1.8,
                    help="dB trim after the limiter, for inter-sample peaks")
    ap.add_argument("--fade-in", type=float, default=3.0)
    ap.add_argument("--fade-out", type=float, default=10.0)
    a = ap.parse_args()

    P = json.load(open(a.plan))
    plan, X, total = P["plan"], P["xfade"], P["total"]
    bar = P.get("bar_seconds") or 2.0
    target_bpm = P.get("target_bpm")

    lock = bool(target_bpm) and not a.no_tempo_lock
    if lock and not shutil.which("rubberband"):
        sys.exit("plan asks for a tempo lock but rubberband is not on PATH "
                 "(brew install rubberband) -- or pass --no-tempo-lock")

    xn = int(round(X * SR))
    tmpdir = os.path.join(os.path.dirname(os.path.abspath(a.out)) or ".", ".pdj_seg")
    os.makedirs(tmpdir, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)

    raw_path = os.path.join(tmpdir, "raw.wav")
    sink = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "2",
         "-i", "-", "-c:a", "pcm_f32le", raw_path],
        stdin=subprocess.PIPE)

    def emit(block):
        sink.stdin.write(np.asarray(block, dtype=np.float32).tobytes())

    print(f"{len(plan)} segments, {X:.2f}s ({P.get('crossfade_bars') or '-'} bar) "
          f"crossfades, {'adaptive' if not a.no_adaptive else 'plain'} bass"
          + (f", tempo locked to {target_bpm:.2f} BPM" if lock else ", no tempo lock"))

    tail = None
    for i, p in enumerate(plan):
        x = prepare_segment(p, tmpdir, lock)
        if tail is None:
            emit(x[:len(x) - xn])
        else:
            emit(crossfade(tail, x[:xn], bar, a.highpass, not a.no_adaptive))
            emit(x[xn:len(x) - xn] if i < len(plan) - 1 else x[xn:])
        tail = x[len(x) - xn:] if i < len(plan) - 1 else None
        print(f"  {p['index']:>3}/{len(plan)}  {p['title'][:38]:<38} "
              f"{'%+.2f%%' % ((p.get('stretch', 1) - 1) * 100) if lock else '':>8}")

    sink.stdin.close()
    if sink.wait() != 0:
        shutil.rmtree(tmpdir, ignore_errors=True)
        sys.exit("writing the raw mix failed")

    # Measure the raw mix and correct. Long crossfades mean a large share of the
    # set is a blend of two tracks; per-segment gains alone cannot predict where
    # the integrated value lands.
    import re as _re
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", raw_path,
                          "-af", "ebur128", "-f", "null", "-"],
                         capture_output=True, text=True).stderr[-2000:]
    m = _re.search(r"I:\s*(-?\d+\.?\d*)\s*LUFS", err)
    raw_lufs = float(m.group(1)) if m else a.target_lufs
    gain = a.target_lufs - raw_lufs
    print(f"raw mix {raw_lufs:.1f} LUFS -> correcting {gain:+.1f} dB")

    master = (f"volume={gain:.2f}dB,"
              f"afade=t=in:st=0:d={a.fade_in},"
              f"afade=t=out:st={total - a.fade_out:.2f}:d={a.fade_out},"
              f"alimiter=level_in=1:level_out=1:limit=0.891:attack=5:release=60,"
              f"volume={a.tp_trim}dB")
    rc = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw_path,
                         "-af", master, "-c:a", "pcm_s16le", a.out]).returncode
    shutil.rmtree(tmpdir, ignore_errors=True)
    if rc != 0:
        sys.exit(f"master stage failed with code {rc}")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
