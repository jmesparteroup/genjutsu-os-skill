# Operating the staged workflow

Use a source clip with audible speech and a character reference supplied by the user. The source must be 4–15 seconds, within 85 ms of a whole second, with aligned video/audio start times. This skill does not silently crop, stretch, trim or re-time inputs. Normalized video is 24 fps and at most 960 pixels on either side; both sides must remain at least 300 pixels and the aspect ratio must be 0.4–2.5 for Seedance. Character images are limited to 30 MB and reference video to 200 MB.

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

## Paid preparation (only when authorized)

```bash
python3 "$skill_dir/scripts/genjutsu.py" prepare --run "$run_dir" --execute --allow-paid
```

Each invocation submits at most one new model request and polls it once. Repeat while paid preparation remains authorized until all three preparation outputs are downloaded. Once a request exists, `--execute` without `--allow-paid` can collect it but will stop before the next new paid stage. No busy polling: wait about 10 seconds between pending checks. This is deliberately compatible with CMA's tool-call and turn boundaries; an interrupted turn can continue with the same run directory.

Outputs: `vocals.wav`, `depth.mp4`, and `segmentation-candidate.mp4`. SAM uses the depth output, `apply_mask=false`, and no bounding-box archive. Actual mask semantics remain untested. A colored overlay or masked RGB video is not a white-subject/black-background mask. If the candidate is unsuitable, stop; obtaining a valid mask may require an explicitly approved alternative. The skill accepts a supplied binary mask and does not pretend that conversion is always possible.

## Build the review artifact locally

```bash
python3 "$skill_dir/scripts/genjutsu.py" build-review --run "$run_dir" \
  --mask /workspace/input/verified-white-subject-mask.mp4
python3 "$skill_dir/scripts/genjutsu.py" export --run "$run_dir" \
  --output-dir /mnt/session/outputs
```

If the inspected SAM candidate is actually a binary mask, pass its path instead. Validation decodes every frame before grayscale conversion, checks uninterrupted 24 fps timestamps, dimensions and frame count against working/depth videos, and rejects substantial color or intermediate gray. These checks cannot prove correct subject selection or polarity. `mask-report.json` contains per-frame white coverage to aid review. `prepared-review.mp4` embeds pitched vocals over the composite. The source and original audio remain unchanged.

Show the exported mask and full review video to the human through the host's media/download interface. Ask for review of the whole clip; stop the agent turn while awaiting the answer. The host must preserve and deliver the actual user's response.

Only after that response:

```bash
python3 "$skill_dir/scripts/genjutsu.py" approve-review --run "$run_dir" \
  --reviewer 'actual reviewer name' --evidence 'actual user message ID or quoted confirmation' \
  --reviewed-full-clip --reviewed-mask
python3 "$skill_dir/scripts/genjutsu.py" generate --run "$run_dir"
```

This records a content-bound acknowledgment and previews the payload without network calls. It is not an independently enforced human-authentication mechanism. Do not fabricate approval, reuse approval from another run, or treat permission to generate as confirmation of unseen masks.

## Paid generation (only when separately authorized)

```bash
python3 "$skill_dir/scripts/genjutsu.py" generate --run "$run_dir" --execute --allow-paid
```

Later pending checks can omit `--allow-paid`. The request always uses `bytedance/seedance-2.5/reference-to-video`, `resolution=480p`, `draft=false`, `task=reference`, exact whole-second duration, and H.264. Local embedding replaces the old hosted merge stage, so no extra FAL FFmpeg jobs are needed. This orchestrator calls the model endpoints directly and creates no saved FAL workflow definitions.

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
