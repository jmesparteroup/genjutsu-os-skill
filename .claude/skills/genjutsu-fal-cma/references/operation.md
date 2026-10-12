# Operating the staged workflow

Use a source clip with audible speech and a character reference supplied by the user. The source must be 4–30 seconds, within 85 ms of a whole second, with aligned video/audio start times. This skill does not silently crop, stretch, trim or re-time inputs. Normalized video is 24 fps and at most 960 pixels on either side; both sides must remain at least 300 pixels and the aspect ratio must be 0.4–2.5 for Seedance. Character images are limited to 30 MB and reference video to 200 MB.

In the examples, `skill_dir` is the discovered absolute skill mount path. Set it to the path CMA reports, not a hardcoded Mac path. `run_dir` must be a new owned directory. No credentials are command arguments.

```bash
skill_dir=/absolute/path/to/genjutsu-fal-cma
run_dir=/workspace/genjutsu-runs/clip-001
python3 "$skill_dir/scripts/doctor.py"
python3 "$skill_dir/scripts/genjutsu.py" init --run "$run_dir" \
  --source /workspace/input/source.mp4 --character /workspace/input/character.png
python3 "$skill_dir/scripts/genjutsu.py" prepare --run "$run_dir"
```

`init` copies original inputs into the run, hashes them, normalizes video, extracts the first audio track as WAV and validates Seedance input constraints. Read-only input mounts work because outputs go into the run. Pass `--subject` to select SAM's target and `--prompt-file` for a custom UTF-8 prompt at initialization. The default prompt references `@Video1` for motion and `@Image1` for identity. Change those choices by creating a fresh run; do not edit state manually.

For two performers, add `--character2 /workspace/input/second-person.png` and a `--prompt-file` that explicitly assigns `@Image1` (the first portrait) and `@Image2` (the second) to their performers. Both portraits are copied, hashed, and bound to the preparation fingerprint. The mask must cover both intended performers throughout the clip; one text prompt does not guarantee that SAM selected both.

## Paid preparation (only when authorized)

```bash
python3 "$skill_dir/scripts/genjutsu.py" prepare --run "$run_dir" --execute --allow-paid
```

Each invocation submits at most one new model request and polls it once. Repeat while paid preparation remains authorized until all three preparation outputs are downloaded. Once a request exists, `--execute` without `--allow-paid` can collect it but will stop before the next new paid stage. No busy polling: wait about 10 seconds between pending checks. This is deliberately compatible with CMA's tool-call and turn boundaries; an interrupted turn can continue with the same run directory.

Outputs: `vocals.wav`, `depth.mp4`, and `segmentation-candidate.mp4`. SAM uses the depth output, `apply_mask=false`, and no bounding-box archive. Actual mask semantics remain untested. A colored overlay or masked RGB video is not a white-subject/black-background mask. If the candidate is unsuitable, stop; obtaining a valid mask may require an explicitly approved alternative. The skill accepts a supplied binary mask and does not pretend that conversion is always possible.

If SAM returns `rle` instead of `video`, preparation saves the response to `segmentation-rle.json` and stops at `mask-required`. Decode that actual data locally, verifying its format, dimensions, frame order, and frame count before using it as a mask. The collector does not decode unknown formats or submit another SAM job. This response shape was observed in a local FAL test; the decoded mask must pass the same automatic checks; manual review is optional.

## Validate and prepare locally

```bash
python3 "$skill_dir/scripts/genjutsu.py" build-review --run "$run_dir" \
  --mask /workspace/input/verified-white-subject-mask.mp4
python3 "$skill_dir/scripts/genjutsu.py" export --run "$run_dir" \
  --output-dir /mnt/session/outputs
```

If the inspected SAM candidate is actually a binary mask, pass its path instead. Validation decodes every frame before grayscale conversion, checks uninterrupted 24 fps timestamps, dimensions and frame count against working/depth videos, and rejects substantial color or intermediate gray. These checks cannot prove correct subject selection or polarity. `mask-report.json` contains per-frame white coverage to aid review. `prepared-review.mp4` embeds pitched vocals over the composite. The source and original audio remain unchanged.

`build-review` records a fingerprint after successful mask validation, compositing and reference checks, then returns `ready-for-generation`. Proceed to generation when paid generation is already authorized; no user mask confirmation or `approve-review` command is required. Exporting the mask/report is optional and does not pause the workflow. Numeric checks validate format and alignment, not perfect subject coverage; correct observed coverage errors before proceeding.

Preview the generation payload without network calls:

```bash
python3 "$skill_dir/scripts/genjutsu.py" generate --run "$run_dir"
```

Changed media or prompt makes preparation stale. Before any generation request exists, rerun `build-review` to validate and rebuild it. Once a request exists, use a fresh run for changed inputs. Older runs with a matching content-bound review record remain usable; older unreviewed runs need `build-review` once to record validation.

`approve-review` remains available only as an optional annotation when a user actually reviews the clip. Never fabricate a human review record to advance the workflow.

## Paid generation (when authorized)

```bash
python3 "$skill_dir/scripts/genjutsu.py" generate --run "$run_dir" --execute --allow-paid
```

Authorization for the full paid workflow already covers this step; ask only if generation has not been authorized. Later pending checks can omit `--allow-paid`. The request always uses `bytedance/seedance-2.5/reference-to-video`, `resolution=480p`, `draft=false`, `task=reference`, exact whole-second duration, and H.264. Local embedding replaces the old hosted merge stage, so no extra FAL FFmpeg jobs are needed. This orchestrator calls the model endpoints directly and creates no saved FAL workflow definitions.

After downloading `generated-480p.mp4`, the tool checks the 480-pixel short side, refuses duration differences above 85 ms, copies the complete first source audio stream into `final-480p.mp4`, and verifies SHA-256 of encoded audio packet bytes. MP4-incompatible source audio fails instead of being silently re-encoded. Additional source audio streams are not copied. No HD fallback, upscaling, auto trimming, or paid retry occurs.

Export again to `/mnt/session/outputs`, then obtain final human visual and lip-sync review. Generated output is for review until that acceptance occurs.

## Recovery

`status --run "$run_dir"` reports saved request IDs without network access. State is written atomically and commands acquire a per-run lock. Media downloads use temporary files and verified local upload caches are reused.

A `submitting` job after a timeout/crash has an unknown outcome. Find the matching request in FAL using the endpoint, input media and time of submission. Obtain its queue response JSON (`request_id`, `status_url`, `response_url`, `cancel_url`) and use:

```bash
python3 "$skill_dir/scripts/genjutsu.py" adopt --run "$run_dir" --job depth \
  --request-json /workspace/reconciled-request.json
```

Do not adopt a different job. If no request ID can be recovered, remain BLOCKED rather than repeating the POST. A confirmed failed job remains recorded; a newly authorized retry uses a fresh run, making its additional charge explicit. FAL may retry internally; this tool does not submit replacement inference automatically.

Treat `state.json` and its media URLs as private run metadata. Preserve it across turn boundaries; reattach the same run directory after host/sandbox replacement rather than rebuilding and paying twice. Re-export state privately if long-term recovery is required, since this skill alone does not guarantee sandbox survival.
