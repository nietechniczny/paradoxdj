---
name: ParadoxDJ
description: Use when someone wants a DJ set, continuous mix, or long-form music video produced end to end — from a concept to a file ready to upload — or when an existing mix needs its transitions, loudness, runtime or looping visuals fixed.
---

# ParadoxDJ

Builds a continuous DJ set of a requested length, with generated music and generated looping visuals, and delivers a file ready to upload.

**Core principle: measure the audio, do not trust what you asked for.** Generative music tools take BPM and duration as suggestions, not contracts. Every decision downstream — running order, segment lengths, in-points, gain — must come from measuring the files you actually got.

## Requirements

| Need | Primary | Equivalents |
|---|---|---|
| Music | Suno (browser) | Udio, Riffusion, an existing library |
| Visuals | higgsfield-mcp | magnific-mcp, any image/video generator, stock loops |
| Assembly | ffmpeg on PATH + Python 3 with numpy | — |
| Title card | Pillow | — |
| Beat analysis (optional) | librosa | skip with `--no-grid` |

Without a music source **and** a visual source you cannot finish. Say so up front rather than delivering half a set.

## Do this first

Never guess these four. One `AskUserQuestion` round:

1. **Runtime** — the whole plan is solved from it.
2. **Genres and energy arc** — or accept the default arc in `plan_set.py`.
3. **Lyric language** — prompt language is a weak signal; house and trance are sung in English by convention. Decide, state the choice, let the user correct it.
4. **Aspect ratio and visual style** — this spends generation credits, so get it right before spending them.

## Track count

Generation slots are the unit of planning. Each track contributes `segment − crossfade` to the set, so:

```
tracks ≈ runtime / (average segment − crossfade)
```

A 60-minute set at ~2:20 segments with 8 s crossfades needs ~28 tracks. **Generate 20–30% more than the arithmetic requires** — some takes come back unusable and you want to drop them, not patch around them.

## Pipeline

All scripts live in `scripts/` next to this file and run standalone
(`python3 scripts/<name>.py --help`). Work in a scratch directory — the steps
pass state to each other through `tracks.json` and `plan.json`.

| Step | Command | Produces |
|---|---|---|
| 1 | `analyze_tracks.py --in AUDIO --out tracks.json` | duration, loudness, loudness curve, beat-grid class |
| 2 | `plan_set.py --tracks tracks.json --target 60:00 --clips CLIPS --out plan.json` | segments, in-points, gains, clip assignment |
| 3 | `build_audio.py --plan plan.json --out mix.wav` | the mix |
| 4 | `verify_mix.py --mix mix.wav --plan plan.json` | pass/fail QC — **run before rendering video** |
| 5 | `make_loops.py --in CLIPS --out loops` | seamless, correctly framed loops |
| 6 | `make_title_card.py --title … --out title.png` | overlay card |
| 7 | `build_video.py --plan plan.json --loops loops --out video.mp4` | picture, frame-aligned to the audio |
| 8 | `publish_assets.py --plan plan.json --mix mix.wav --video video.mp4 …` | MP3, MP4, chapters.txt |

Steps 3 and 7 read the same `plan.json`, which is why every video transition lands on the frame its audio crossfade does. Never hand-align them.

Details: `references/music-generation.md`, `references/visuals.md`, `references/mixing.md`, `references/publishing.md`, `references/troubleshooting.md`.

## Non-negotiables

**Run `verify_mix.py` before rendering video.** Video is the expensive step. A mix with holes at the transitions will still have them after an hour of encoding.

**Never fake beatmatching.** `analyze_tracks.py` classes every track: **A** metronomic, **B** warpable, **C** no stable grid. Generative tracks are frequently C — no DJ software can lock to those either. Either exclude them (`--exclude-class C`), regenerate them, or say plainly that the set is crossfaded rather than beatmatched.

**Never solve a CAPTCHA or bot check.** Suno throws Cloudflare challenges during long runs. Stop, tell the user, wait. The page reload also clears the form, so re-check every field before continuing.

**Disclose synthetic content.** AI-generated music and visuals must be labelled on YouTube. Put it in the description and set the flag in Studio.

## Common mistakes

| Mistake | What happens | Fix |
|---|---|---|
| Fixed in-point (e.g. always 20 s) | Tracks enter on a quiet verse; the bass swap leaves an audible hole | `plan_set.py` scores in-points by energy at entry, body and exit |
| Plain crossfade | Two kicks and two basslines stack up, low end turns to mud | Bass-swap: high-pass the outgoing track through the fade |
| Trusting the generator's BPM | Running order is built on numbers the files do not have | Sort by measured BPM from `analyze_tracks.py` |
| Trusting the generator's duration | Set lands minutes off target | Measure with ffprobe; `plan_set.py` solves lengths from real durations |
| Limiting to −1 dBFS sample peak | True peak still clips (inter-sample) | Limit, then trim; verify true peak ≤ −1.0 dBFS |
| Looping a clip with `-stream_loop` alone | Visible jump every repeat | `make_loops.py` crossfades the clip's tail into its head |
| Clicking browser UI by coordinates | Layout shifts, clicks land on the wrong control | Use element references; re-read the page after any reload |
