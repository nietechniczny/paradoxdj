"""Shared DSP helpers. numpy only -- no scipy, no librosa at import time."""
import subprocess
import numpy as np

SR = 44100


def decode(path, sr=SR, mono=False, start=None, dur=None):
    """Decode audio to float32 via ffmpeg. Returns (n,) mono or (n,2) stereo."""
    cmd = ["ffmpeg", "-v", "error"]
    if start is not None:
        cmd += ["-ss", str(start)]
    if dur is not None:
        cmd += ["-t", str(dur)]
    cmd += ["-i", path, "-ac", "1" if mono else "2", "-ar", str(sr), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    return x if mono else x.reshape(-1, 2)


def fft_split(x, sr, cutoff, width=40.0):
    """Linear-phase split into (low, high) that sum back to x exactly.

    A smooth raised-cosine transition of `width` Hz avoids the ringing a brick
    wall would produce. Used for the bass handover, where the two bands are
    mixed with different laws and must recombine without a notch.
    """
    n = len(x)
    ch = x.reshape(n, -1)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    lo_gain = np.ones_like(freqs)
    hi_edge = cutoff + width / 2
    lo_edge = cutoff - width / 2
    band = (freqs > lo_edge) & (freqs < hi_edge)
    lo_gain[freqs >= hi_edge] = 0.0
    lo_gain[band] = 0.5 * (1 + np.cos(np.pi * (freqs[band] - lo_edge) / width))
    low = np.empty_like(ch)
    for c in range(ch.shape[1]):
        spec = np.fft.rfft(ch[:, c])
        low[:, c] = np.fft.irfft(spec * lo_gain, n=n)
    low = low.reshape(x.shape)
    return low, x - low


def kick_envelope(mono, sr, lo=38.0, hi=95.0, fps=200.0):
    """Rectified energy of the kick band, at `fps` frames per second.

    Beat trackers latch onto whatever is most periodic, which in dance music is
    often the hi-hat or the offbeat. Locking the grid to the kick instead gives
    a phase that matches what a listener hears as the pulse.
    """
    n = len(mono)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    spec = np.fft.rfft(mono)
    spec[(freqs < lo) | (freqs > hi)] = 0
    band = np.abs(np.fft.irfft(spec, n=n))
    hop = max(1, int(sr / fps))
    m = len(band) // hop * hop
    env = band[:m].reshape(-1, hop).max(axis=1)
    d = np.diff(env, prepend=env[0])
    d[d < 0] = 0
    return d / (d.max() + 1e-12), sr / hop


def grid_phase(env, fps, bpm, subdiv=1):
    """Offset in seconds that best aligns a click train at `bpm` to `env`."""
    period = fps * 60.0 / bpm / subdiv
    n = len(env)
    best, score = 0.0, -1.0
    for off in np.arange(0, period, 0.25):
        idx = np.round(np.arange(off, n - 1, period)).astype(int)
        idx = idx[(idx >= 0) & (idx < n)]
        if not idx.size:
            continue
        s = float(env[idx].mean())
        if s > score:
            best, score = off / fps, s
    return best, score


def downbeat_offset(mono, sr, bpm, beat_phase, beats_per_bar=4):
    """Which of the N beats starts the bar.

    The kick is on every beat in four-to-the-floor, so the downbeat has to be
    found from something else: bar starts carry crashes, chord changes and
    other broadband transients. Score each candidate on full-band novelty.
    """
    n = len(mono)
    hop = max(1, int(sr / 200.0))
    m = len(mono) // hop * hop
    env = np.abs(mono[:m]).reshape(-1, hop).max(axis=1)
    d = np.diff(env, prepend=env[0])
    d[d < 0] = 0
    d = d / (d.max() + 1e-12)
    fps = sr / hop
    beat = 60.0 / bpm
    best, score = 0, -1.0
    for k in range(beats_per_bar):
        t0 = beat_phase + k * beat
        idx = np.round((np.arange(t0, n / sr - beat, beat * beats_per_bar)) * fps).astype(int)
        idx = idx[(idx >= 0) & (idx < len(d))]
        if not idx.size:
            continue
        s = float(d[idx].mean())
        if s > score:
            best, score = k, s
    return best, score


def bar_power(low, sr, bar_seconds, n_bars):
    """RMS of the low band in each bar. Drives the adaptive bass handover."""
    out = np.zeros(n_bars)
    step = int(round(bar_seconds * sr))
    mono = low.mean(axis=1) if low.ndim > 1 else low
    for i in range(n_bars):
        a, b = i * step, min((i + 1) * step, len(mono))
        if b > a:
            out[i] = float(np.sqrt(np.mean(mono[a:b] ** 2)))
    return out


def adaptive_bass_weight(pa, pb, base, floor=1e-6):
    """Weight for the INCOMING track's low band, per bar.

    `base` is the plain time ramp (0 -> 1 across the transition). Reweighting it
    by the two tracks' actual bass power means the low end is always carried by
    whichever track has one. When the outgoing track drops its bass mid-fade --
    which is common, breakdowns happen -- the incoming track takes over early
    instead of leaving a hole.
    """
    pa = np.maximum(pa, floor)
    pb = np.maximum(pb, floor)
    num = base * pb
    return num / (num + (1.0 - base) * pa + 1e-12)


def power_norm(w, p=1.5):
    """Normaliser for a two-source blend with weights (1-w) and w.

    p=1 leaves it as equal-gain (correct for perfectly coherent sources, e.g.
    two kicks locked to the same grid); p=2 is full equal-power (correct for
    uncorrelated sources). Bass at a transition is somewhere in between, so the
    default splits the difference and avoids both the 3 dB hole and the bump.
    """
    return 1.0 / (((1.0 - w) ** p + w ** p) ** (1.0 / p) + 1e-12)


def equal_power(n):
    """Equal-power crossfade pair. Constant total power on uncorrelated material."""
    t = np.linspace(0.0, 1.0, n, dtype=np.float64)
    return np.cos(t * np.pi / 2), np.sin(t * np.pi / 2)


def smooth_ramp(values, n):
    """Expand per-bar values to per-sample with linear interpolation."""
    if len(values) == 1:
        return np.full(n, values[0])
    xp = np.linspace(0, n - 1, len(values))
    return np.interp(np.arange(n), xp, values)
