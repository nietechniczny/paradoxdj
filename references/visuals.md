# Generating the visuals

## How many, and how long

A dozen to twenty clips carries an hour. Clips are looped to fill each segment
and cross-faded at every track change, so more clips buys variety, not runtime.
Ten seconds each is plenty; anything longer costs credits without helping.

Assign clips to phases — calm geometry for the warm-up and outro, hard-edged
motion for the peaks — and never place the same clip in adjacent segments.
`plan_set.py` assigns them and `build_video.py` enforces the no-repeat rule.

## Prompting for something that actually loops

The model has no concept of a loop. What makes a clip loopable is motion with
no beginning and no end, so say it explicitly and repeatedly:

- **locked static camera**, no zoom, no push-in, no turns
- **absolutely constant speed** — no acceleration, no deceleration
- **cyclical motion** that returns to its starting configuration
- state outright that *the final frame matches the first frame*
- for travelling shots, "flies forward at constant speed through an infinite
  tunnel" loops; a camera that arrives somewhere does not
- for particles, "entering one side exactly as identical particles exit the
  other"
- **negatives matter:** `no fade in, no fade out, no cuts, no text, no logos,
  no people, no faces`

Faces and hands wreck loops and draw the eye away from the music. Abstract light
geometry is the safe default: it loops cleanly, reads at any size, and does not
date.

Even so, generated clips rarely close the loop exactly. `make_loops.py`
crossfades the tail into the head, which removes the residual jump.

## higgsfield-mcp

Model `minimax_h3`: 4–15 s, `resolution: "2K"`, aspect ratios from 21:9 to 9:16,
`batch_size` 1–4.

- `generate_video_batch` takes up to 12 requests; **expect partial failures**.
  Rate limits (429) and preset recommendations both come back as
  `submission_failed`. Re-submit the failures; pass `declined_preset_id` to
  suppress a preset suggestion.
- Preflight with `get_cost: true` and check `balance` before a large batch.
- Poll with `jobs_wait` in groups of 12.

## Aspect ratio

Decide before spending credits. Vertical clips in a 16:9 set must be
centre-cropped, which throws away most of the frame — fine for abstract
patterns, destructive for anything composed. If the set is going to YouTube,
generate 16:9 and crop to vertical later if you need shorts, not the reverse.
