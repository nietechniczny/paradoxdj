# Publishing

## Title

Artist and set name first (brand), genre span in the middle (what people
actually search), runtime and BPM range last (format promise). Under 100
characters.

```
Matt Paradox - NORTHBOUND | 1 Hour Melodic House to Uplifting Trance Mix (120-140 BPM)
```

Offer alternatives rather than one option: a search-first variant with the genre
leading (young channels get no name searches), a CTR-first variant leading with
the concept, and one built on the energy arc.

## Description

The first two lines are all anyone sees before "show more". No greetings, no
channel boilerplate — open with the concept in concrete terms.

Then: a paragraph on the arc, the full tracklist with timestamps, credits,
a note on the visuals, and the AI disclosure.

## Chapters

`publish_assets.py` writes `chapters.txt`. YouTube converts timestamps to
chapters only if **the first is `0:00`**, there are **at least three**, and each
is **at least 10 seconds** long. A second list of timestamps elsewhere in the
description can break parsing — describe the energy arc in prose, without times.

## Disclosing AI

Generated music and visuals must be labelled. Do both:

- a line in the description that separates what was generated from what was
  done by hand ("music written with Suno, visuals with MiniMax H3; tracklist,
  transitions and mix assembled by hand")
- the **Altered or synthetic content** flag in YouTube Studio

Being specific reads as craft. Getting labelled by YouTube instead reads as
evasion.

## Files to hand over

| File | Purpose |
|---|---|
| `<name>.mp3` | 320 kbps, tagged — distribution and local play |
| `<name> 1080p.mp4` | H.264 + AAC, faststart — the upload |
| `chapters.txt` | paste into the description |
| tracklist / notes | timestamps, phases, and what was done to the audio |

State the mastering numbers — integrated LUFS, LRA, true peak — so the user can
check them against whatever platform they publish on.
