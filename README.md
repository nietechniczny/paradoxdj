# ParadoxDJ

A Claude Code skill that builds a continuous DJ set of a requested length — generated music, generated looping visuals, a measured mixdown — and hands back an MP3, an MP4 and a chapter list ready to upload.

It is an [Agent Skill](https://docs.claude.com/en/docs/agents-and-tools/agent-skills): a `SKILL.md` with YAML frontmatter, reference notes in `references/`, and eight Python scripts in `scripts/`. The scripts are the actual tool; the skill text is what teaches Claude to drive them in the right order and to stop when something is wrong.

The governing idea is one sentence long: **measure the audio, do not trust what you asked for.** Generative music tools treat BPM and duration as suggestions. Every downstream decision — running order, segment lengths, in-points, gain — is computed from the files that came back, not from the prompt that produced them.

---

## Requirements

ParadoxDJ assembles; it does not generate. You bring a music source and a picture source.

| Need | Primary | Equivalents |
|---|---|---|
| Music | Suno (browser — **there is no API**) | Udio, Riffusion, your own library |
| Visuals | higgsfield-mcp | magnific-mcp, any image/video generator, stock loops |
| Assembly | `ffmpeg` on PATH + Python 3 with `numpy` | — |
| Title card | `Pillow` | — |
| Beat-grid analysis (optional) | `librosa` | skip it with `--no-grid` |

Without both a music source **and** a visual source the skill cannot finish, and it is written to say so up front rather than deliver half a set.

Scratch files are written to `/tmp`, so on Windows use WSL.

---

## Install

As a Claude Code skill:

```bash
git clone https://github.com/nietechniczny/paradoxdj.git
mkdir -p ~/.claude/skills
cp -R paradoxdj ~/.claude/skills/paradoxdj
```

Restart Claude Code. The skill loads when you ask for a DJ set, a continuous mix or a long-form music video — or when an existing mix needs its transitions, loudness, runtime or looping visuals fixed.

The scripts have no dependency on Claude. They are plain argparse CLIs and run on their own:

```bash
pip install numpy pillow      # librosa too, if you want beat-grid classification
python3 scripts/plan_set.py --help
```

---

## Quick start

Standalone, assuming `audio/` holds your tracks and `clips/` holds short video clips:

```bash
# 1. measure everything you actually got
python3 scripts/analyze_tracks.py --in audio --out tracks.json

# 2. solve a 60-minute set: segment lengths, in-points, gains, clip assignment
python3 scripts/plan_set.py --tracks tracks.json --target 60:00 \
    --clips clips --out plan.json

# 3. render the mix
python3 scripts/build_audio.py --plan plan.json --out mix.wav

# 4. quality gate — exits 1 on failure, so it can gate the rest
python3 scripts/verify_mix.py --mix mix.wav --plan plan.json

# 5-7. picture, built from the same plan.json the audio was
python3 scripts/make_loops.py --in clips --out loops
python3 scripts/make_title_card.py --title "NORTHBOUND" --artist "Matt Paradox" --out title.png
python3 scripts/build_video.py --plan plan.json --loops loops \
    --title-card title.png --out video.mp4

# 8. deliverables
python3 scripts/publish_assets.py --plan plan.json --mix mix.wav --video video.mp4 \
    --outdir out --name "NORTHBOUND - Matt Paradox" --artist "Matt Paradox"
```

Useful flags: `--target-bpm auto` (tempo lock and bar quantisation), `--exclude-class C` (drop tracks with no stable beat grid), `--no-grid` (skip the slow analysis), `--dry-run` on both build steps (print the ffmpeg command and stop), `--order` (supply your own running order, one filename per line).

---

## Pipeline

| Step | Script | Produces |
|---|---|---|
| 1 | `analyze_tracks.py` | duration, integrated LUFS, true peak, a short-term loudness curve, beat-grid class |
| 2 | `plan_set.py` | segments, in-points, gain corrections, clip assignment → `plan.json` |
| 3 | `build_audio.py` | the mix, with bass-swap crossfades, limiter and true-peak trim |
| 4 | `verify_mix.py` | pass/fail QC — **run before rendering video** |
| 5 | `make_loops.py` | seamless, correctly framed loops |
| 6 | `make_title_card.py` | title card as a transparent PNG |
| 7 | `build_video.py` | picture, frame-aligned to the audio |
| 8 | `publish_assets.py` | MP3 (320 kbps, tagged), MP4 (faststart), `chapters.txt` |

Steps 3 and 7 read the same `plan.json`. That is the whole reason every video transition lands on the frame its audio crossfade does, with no manual alignment and no drift over an hour.

Step 4 comes before step 5 on purpose. Video is the expensive step, in credits and in wall-clock time; a mix with holes at the transitions will still have them after an hour of encoding.

Longer notes live in `references/`: `music-generation.md`, `visuals.md`, `mixing.md`, `publishing.md`, `troubleshooting.md`.

---

## How it works

### It measures instead of believing

`analyze_tracks.py` runs `ffprobe` and `ebur128` over every file and writes down what is really there: duration to the millisecond, integrated loudness, true peak, and a short-term loudness curve sampled twice a second. `plan_set.py` then *solves* for runtime rather than estimating it — with `n` segments and a crossfade of `X` seconds the set is `Σ segᵢ − (n−1)·X`, so it distributes `target + (n−1)·X` across the segments weighted by an energy arc, clamps each to what its file can actually supply, and redistributes the slack. The planned total lands on the target to the second.

Requested durations are worth nothing here. Suno takes `Duration: Custom` as a hint; a request for 4:15 has come back at 3:21 and at 7:59.

### Bass swap, not crossfade

A plain crossfade between two dance tracks puts two kicks and two basslines on top of each other for the length of the fade. The low end doubles, the result is mud, and any tempo difference is most audible down there.

`build_audio.py` does what a DJ does, and does it adaptively. Both tracks are split at 180 Hz with a linear-phase FFT crossover; the high band crossfades equal-power, and the low band is handed over by a weight computed **per bar from the bass power of both tracks** — `w = base·pB / (base·pB + (1−base)·pA)`. Only one low end is ever playing, and when the outgoing track drops its bass mid-transition the incoming track takes over early instead of leaving a hole. A static high-pass cannot do that; it strips the bass on a schedule whether or not there is any there.

### Tempo lock

Pass `--target-bpm auto` and every track is time-stretched to one tempo with `rubberband` before mixing. That is what beatmatching actually is. With the tempo locked, segments become whole bars, the crossfade is a whole number of bars, and in-points snap to downbeats — found by locking the grid to the 38–95 Hz kick envelope rather than to whatever a beat tracker latched onto.

Tracks needing more than `--max-stretch` percent (default 6) are dropped rather than mangled. On a six-track test the tempo spread across the finished mix fell from 5.20 BPM to 0.50 BPM.

### In-points chosen by energy

The obvious approach is a fixed offset: start every track 20 seconds in, past the intro. It is appealing and it is wrong — some tracks are in a sparse verse at 0:20, and since the transition strips the bass off the *outgoing* track, an incoming track with no energy has nothing to fill the gap with.

Measured on a real 28-track set: a fixed in-point gave **15 of 27 transitions with a loudness hole, some as deep as 7 LU.**

`plan_set.py` now scores every candidate start:

| Weight | Window | Why |
|---|---|---|
| 0.40 | first 10 s | the track must enter with punch |
| 0.20 | whole segment | overall level |
| 0.30 | last 10 s | it must exit with punch too, for the next transition |
| 0.10 | minimum of last 10 s | no breakdown at the hand-off |

Same set, same tracks, scored in-points: **one hole left, and 26 of 27 transitions inside ±2 LU.** Chosen in-points tend to land on drops, which is where a DJ would drop the needle anyway.

---

## Limits

**It does not beatmatch unstable material, and it will not pretend to.** `analyze_tracks.py` fits a constant tempo grid to each track and classes it:

| Class | Meaning | What happens |
|---|---|---|
| A | residual < 25 ms, drift < 0.4% — metronomic | beatmatchable |
| B | drift < 1% | fine for crossfades, and stretched to the set tempo under `--target-bpm` |
| C | drift ≥ 1%, no stable grid | regenerate, exclude, or accept a crossfaded set |

Generative tracks are frequently class C. This is a property of the audio, not of the analysis: Rekordbox, Traktor and Serato all build a constant grid and fail on those files for the same reason. When a set contains class C tracks, the honest description is **crossfaded, not beatmatched** — and the skill is written to say that out loud rather than let it pass. With the bass swap, a crossfaded set is what most listeners hear as clean anyway; that is not an excuse to relabel it.

Other things worth knowing before you start:

- **Tempo search is bounded to 100–160 BPM.** Outside that range the grid fit is not meaningful; use `--no-grid` and treat the set as crossfaded.
- **Suno has no API.** The music step means driving a web app, and it throws Cloudflare challenges on long runs. The skill stops and asks you to clear them; it never solves a bot check. Pacing generations about 30 s apart makes them much rarer.
- **Generate 20–30% more tracks than the arithmetic needs.** Some takes come back unusable and you want to drop them, not patch around them.
- **Generated clips do not close their loops.** `make_loops.py` crossfades the tail into the head, which costs one second of clip length (`--blend`) and removes the visible jump. Vertical clips in a 16:9 set are centre-cropped — fine for abstract motion, destructive for anything composed. Decide aspect ratio before spending credits.
- **Renders are large and slow.** An hour of 1080p is 2–3 GB. `h264_videotoolbox` is detected automatically on Apple silicon; `libx264 -crf 20` is the portable fallback and much slower.
- **Homebrew's ffmpeg has no `drawtext`**, which is why the title card is rasterised with Pillow and composited as a PNG. `rubberband` is usually missing too; install the CLI binary separately if you want true time-stretching.
- **`make_title_card.py` needs a TrueType font.** It probes the usual macOS/Linux/Windows paths and exits if it finds none — pass `--font /path/to/font.ttf`.
- **`publish_assets.py` produces files; it does not upload.** YouTube turns `chapters.txt` into chapters only if the first entry is `0:00`, there are at least three, and each is at least 10 seconds long.

### Synthetic content must be disclosed

AI-generated music and visuals have to be labelled on YouTube. Do both: a line in the description that separates what was generated from what was done by hand, and the **Altered or synthetic content** flag in YouTube Studio. Being specific about it reads as craft. Getting labelled by the platform instead reads as evasion.

---

## License

MIT.

Built by M4B.
