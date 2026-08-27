# Environment traps

Every one of these cost real time. Check before building, not after.

## ffmpeg

**`drawtext` is often not compiled in.** Homebrew's ffmpeg 8.x has no
`drawtext`, so overlaying text fails at filter-graph parse time. Rasterise text
to a transparent PNG (`make_title_card.py`) and `overlay` it. Works everywhere.

Check what you have before designing a filter graph:

```bash
ffmpeg -hide_banner -filters | grep -E "drawtext|xfade|overlay|rubberband"
```

**`rubberband` is usually not compiled in either.** Use the CLI binary
(`brew install rubberband`) as a separate pass. `atempo` is the fallback but
smears transients beyond about ±5%.

**Order of options matters.** `-map_metadata -1` before the first `-i` is parsed
as an input option and aborts the run. Output options go after all inputs.

**Long filter graphs belong in a file.** Use `-filter_complex_script`; a
28-segment graph on the command line hits argument limits and is unreadable.

**Encoders.** `h264_videotoolbox` renders an hour of 1080p at roughly 9× real
time on Apple silicon. `libx264 -crf 20 -preset medium` is the portable
fallback and much slower. Detect rather than assume.

## Python

**`librosa.feature.tempo` is bin-quantised.** It returns values snapped to a
log-spaced grid (123.05, 129.20, 136.00 …), useless for beat-locking. Use it as
a seed, then refine with a comb filter — `analyze_tracks.py` does this.

**`madmom` is abandoned** and does not build on modern Python. **librosa 1.0**
dropped the `numba` dependency and installs cleanly on Python 3.13/3.14.

**Fitting a grid to detected beats needs care.** Assigning beats to indices with
`round((t − anchor)/period)` breaks silently: over hundreds of beats a 1% tempo
error accumulates past half a beat and indices wrap, producing residuals that
look like drift but are a bug. Index from consecutive inter-beat intervals
instead, allowing for skipped beats.

## Shell and tooling

**Browser `wait` actions cap at 10 s.** Chain several for longer pauses.

**Foreground commands time out at 2 minutes.** Anything longer — an hour of
video encoding — goes in the background with a completion check.

**A 60-minute 1080p render is 2–3 GB.** Check free space before starting.

## Sanity checks before delivering

```bash
ffprobe -v error -show_entries format=duration -of csv=p=0 out.mp4   # runtime
ffmpeg -i out.mp4 -af ebur128=peak=true -f null -                    # LUFS, true peak
ffmpeg -ss 6 -i out.mp4 -frames:v 1 /tmp/f.jpg                       # look at a frame
```

Look at frames from the title card, a transition and a peak. Rendering
succeeds and still produces a black video more often than you would like.
