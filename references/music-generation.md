# Generating the music

## Writing the prompts

Use the `songwright` skill if it is installed — it handles prosody, rhyme and
Suno's tag vocabulary. Otherwise, per track produce three blocks:

**Lyrics.** Dance tracks are hook-driven, not verse-chorus-bridge pop. Use
Suno's documented section tags — `[Intro]`, `[Verse]`, `[Build-up]`, `[Drop]`,
`[Hook]`, `[Breakdown]`, `[Outro]`. `[Pre-Drop]` and `[Final Drop]` are **not**
recognised; write `[Build-up]` and `[Drop - final, …]`. Performance directions
belong inside the tag, in English. Anything outside a tag gets sung.

**Style prompt.** Around 400 characters, priorities first because truncation
eats the end:

```
[BPM]. [Genre], [Subgenres]. [Character]. [Instruments]. [Vocal]. [Production].
Mood: [5-8 words]. FOCUS: [2-3 elements].
```

**Exclude styles.** Opposites of the genre plus its typical failure modes. Never
exclude anything the style prompt asks for.

## Driving Suno in the browser

Suno has no API. Drive the web app, and expect these:

- **The lyrics box is a contenteditable div**, not a form field. `form_input`
  fails on it. Click it, select all, type.
- **Typing long text reports a CDP timeout that is a false negative.** The text
  usually landed. Screenshot to confirm rather than retyping — retyping
  duplicates it.
- **Click by element reference, never by coordinate.** The panel's height
  changes with lyric length, so fixed coordinates drift onto the wrong control.
  A misplaced click silently flipped Lyrics mode from `Write` to `Prompt` in
  testing, which makes Suno treat lyrics as a description to rewrite.
- **Re-assert mode and vocal gender before every generation.** They reset.
- **Sliders are custom divs.** `form_input` fails; drag them, or focus and use
  arrow keys, then zoom in to read the value back.
- **`Duration: Custom` is a hint.** Requests of 4:15 have come back at 3:21 and
  at 7:59. Measure afterwards; never plan on the requested value.
- **Cloudflare challenges appear during long runs.** Do not solve them. Stop,
  tell the user, wait. The reload clears the form — re-fill and re-verify
  every field, including the mode toggle.
- **Pace the run.** ~30 s between generations markedly reduces challenges.

## The quality gate

Run `analyze_tracks.py` on everything before planning. It classes each track:

| Class | Meaning | Action |
|---|---|---|
| **A** | rms < 25 ms, drift < 0.4% — metronomic | beatmatch freely |
| **B** | drift < 1% | fine for crossfades; warpable with rubberband |
| **C** | drift ≥ 1%, no stable grid | regenerate, or exclude, or accept a crossfaded set |

Class A tempos come back on suspiciously round numbers (121.003, 128.001) —
that is the generator's clock holding steady. Class C tracks wander by several
BPM across their length; Rekordbox, Traktor and Serato all build a *constant*
grid and fail on them for the same reason. This is a property of the audio, not
of the analysis tool.

The cheapest fix is regeneration: generate, measure, keep only takes that pass.
Budget for it — that is why you generate 20–30% more tracks than you need.

## Downloading

Suno's CDN serves `https://cdn1.suno.ai/<clip-id>.mp3` once a clip finishes
processing. A **403 means "still rendering"**, not "forbidden" — the page shows
*Preparing song for playback*. Wait and retry rather than switching versions.

Clip IDs come from `/song/<id>` links in the DOM. The list is virtualised and
paginated, so scroll each page and follow "next page" until the collected set
stops growing.
