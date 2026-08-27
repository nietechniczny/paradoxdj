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

## The bass swap

A plain crossfade puts two kicks and two basslines on top of each other. The low
end doubles, the result is muddy, and any tempo difference is most audible down
there.

`build_audio.py` high-passes the outgoing track for the length of the
transition — two poles at 180 Hz, with +4 dB makeup for the energy lost — while
the incoming track arrives full-range. Only one low end plays at a time. This
is standard DJ technique and it also hides the fact that the tracks are not
beatmatched, because the clash you hear when kicks fight is a *low-frequency*
clash.

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
