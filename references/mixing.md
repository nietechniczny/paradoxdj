# Assembling the mix

## Solving for runtime

With `n` segments and a crossfade of `X` seconds, each segment contributes
`seg − X` except the last:

```
runtime = Σ segᵢ − (n − 1)·X
```

`plan_set.py` inverts this: it distributes `runtime + (n−1)·X` across the
segments weighted by the energy arc, clamps each to what its file can supply,
and redistributes the slack. The planned total lands on the target to the
second. Do not eyeball segment lengths.

Segments grow with energy — roughly 1:50 in the warm-up, 2:45 at the peak,
2:10 in the outro. The climax gets the most room; the entrance and the exit do
not drag.

## Choosing in-points

This is the single decision that separates a mix that breathes from one full of
holes, and it is the one most easily got wrong.

A fixed offset — "start every track 20 seconds in, past the intro" — is
appealing and wrong. Some tracks are in a sparse verse at 0:20. Because a
DJ-style transition strips the low end off the *outgoing* track, an incoming
track with no energy has nothing to fill the gap with, and the mix drops out.
Measured on a real 28-track set: **15 of 27 transitions fell by up to 7 LU.**

`plan_set.py` scores every candidate start by four terms:

| Weight | Window | Why |
|---|---|---|
| 0.40 | first 10 s | the track must enter with punch |
| 0.20 | whole segment | overall level |
| 0.30 | last 10 s | it must *exit* with punch too, for the next transition |
| 0.10 | minimum of last 10 s | no breakdown at the hand-off |

Adding the exit terms took that same set from 15 bad transitions to 1, with 26
of 27 inside ±2 LU. In-points land on drops, which is where a DJ would drop the
needle anyway.

## Tempo lock

Beatmatching means one tempo for the whole set. `--target-bpm auto` takes the
median of the measured tempos; `build_audio.py` stretches every segment to it
with `rubberband` before mixing. Anything needing more than `--max-stretch`
percent (default 6) is dropped from the set rather than mangled — beyond about
6% the artefacts on transients are audible.

With the tempo locked, everything else can be counted in bars instead of
seconds: segment lengths are whole bars, the crossfade is a whole number of bars
(default 8), and in-points snap to the track's downbeat. The set then lands a
bar or two off the requested runtime rather than exactly on it — that is the
price of musical boundaries, and it is worth paying.

Finding the downbeat needs care. In four-to-the-floor the kick is on every beat,
so a beat tracker's phase is not the one a listener feels — it latches onto
whatever is most periodic, frequently the hi-hat or the offbeat.
`analyze_tracks.py` locks the grid to the 38–95 Hz kick envelope, then picks
which of the four beats starts the bar from full-band novelty, because bar
starts carry crashes and chord changes that the other three beats do not.

Measured on a six-track test: tempo spread across the finished mix fell from
5.20 BPM to 0.50 BPM.

## The bass swap

A plain crossfade puts two kicks and two basslines on top of each other. The low
end doubles, the result is muddy, and any tempo difference is most audible down
there.

`build_audio.py` splits both tracks at 180 Hz with a linear-phase FFT crossover
that recombines exactly, then treats the two bands differently. The high band
crossfades equal-power. The low band is *handed over*: a weight computed per bar
from the bass power of both tracks decides which one carries it.

```
w = base·pB / (base·pB + (1 − base)·pA)
```

`base` is the plain time ramp; `pA` and `pB` are the two tracks' bass RMS in
that bar. When the outgoing track drops its bass mid-transition — breakdowns
happen, and an 8-bar crossfade is long enough to land in one — the incoming
track takes the low end early instead of leaving a hole. A static high-pass
cannot do that; it removes the bass on a schedule regardless of whether there
is any to remove.

The blend is then normalised by `power_norm` at p = 1.5, between equal-gain
(right for two kicks locked to the same grid) and equal-power (right for
uncorrelated sources). Without it the mix lost about 1 dB overall, because a
long crossfade means a large share of the set is a two-source blend.

Crossfade curves are equal-power (`qsin`). Equal-gain (`tri`) is correct only
for phase-aligned material; on independent tracks it dips in the middle.

## Two kinds of hole

They need different treatment and it is worth keeping them apart.

**At a transition** — the incoming track has nothing to fill the gap the bass
swap opened. That is a defect. `verify_mix.py` fails the build on it.

**Inside a segment** — the chosen fragment contains a breakdown. Often that is
exactly right; tension before a drop is what the music is for. `verify_mix.py`
lists these without failing, so you can look and decide. `plan_set.py` weights
the segment's 10th-percentile loudness at 0.15, which biases in-point choice
away from fragments with a deep hole in them but does not forbid them.

Do not collapse these into one number. Measured on a six-track test, a mix that
reported zero bad transitions still had a passage at −16 LUFS in the middle of
a segment; a transitions-only check said nothing about it.

## Loudness

Measure each segment separately (EBU R128) and gain it to a common target
(default −11 LUFS) *before* the crossfades, so no track jumps out or disappears.
Then limit the finished mix and trim.

**Limiting to −1 dBFS is not enough.** The limiter constrains sample peaks;
inter-sample peaks still overshoot. A mix limited to −1 dBFS measured **+0.5
dBTP**. Apply a trim after the limiter (`--tp-trim`, default −1.8 dB) and verify
with `ebur128=peak=true`.

Aim for −11 to −12 LUFS integrated. YouTube normalises to about −14, so louder
buys nothing there, but the file stays punchy for local and club playback.

## Beatmatching

`analyze_tracks.py` reports whether a constant grid fits. If most tracks are
class A or B and you want true beatmatching:

1. Stretch each segment to a common tempo per phase with `rubberband` — it
   preserves transients far better than ffmpeg's `atempo` beyond ±5%.
2. Quantise segment lengths to whole bars and in-points to downbeats.
3. Ramp tempo *inside* a track at phase boundaries, not across a transition.

If tracks are class C, stop. There is no grid to lock to and no tool will
invent one. Say so, and ship a crossfaded set — which, with the bass swap, is
what most listeners will hear as clean anyway.
