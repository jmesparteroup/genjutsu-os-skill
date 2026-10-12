---
name: genjutsu-fal-cma
description: Use when adapting a supplied speech or performance clip to a character reference with the Genjutsu workflow on FAL, including preparation, automatic subject mask validation, and Seedance 2.5 video generation inside Claude Managed Agents.
---

# Genjutsu on FAL in CMA

Produce a character replacement video using **Seedance 2.5 reference-to-video at 480p**, then restore the complete first original audio stream. Keep the original source unchanged. This is a staged adaptation, not a validated one-click replica of the source workflow.

Read [CMA setup](references/cma-setup.md) for first deployment and dependencies. Read [operation](references/operation.md) when executing. Resolve scripts relative to this skill's directory; invoke them through `python3` or `bash`. Work in a fresh writable run directory outside the skill mount.

## Execution boundaries

- Installation preserves the host's existing skills, packages, networking, credentials, and channel/workspace defaults. The environment templates are for new dedicated sessions; for an existing Daimon channel, follow the merge and recovery steps in [CMA setup](references/cma-setup.md). Never switch a shared channel to a template as an implicit part of skill installation.
- Default to planning and local processing. `prepare` and `generate` submit nothing without `--execute`; a **new** model request additionally requires `--allow-paid`. Add these flags only when the human has authorized the corresponding paid stage. Skill creation, installation, testing, and “don't run paid inference” authorize no model jobs. Uploading source media also requires execution authorization.
- Preparation uses FAL Demucs, turbo-colored Video Depth Anything, and SAM 3 on depth. Pitch vocals locally by +3 semitones with Rubber Band. Composite the white-mask depth subject over the original background, then embed pitched vocals locally.
- Treat SAM's video as a segmentation **candidate**. The API does not promise a binary mask archive. Obtain an aligned white-subject/black-background video mask; the helper inspects every frame and rejects colored/gray overlays and mismatched timelines. If SAM returns an unusable candidate, report BLOCKED and request a suitable mask or authorization for a specific alternative. Do not threshold an overlay, use a bounding-box ZIP as a mask, or silently run paid fallback jobs.
- Run `build-review` to validate the binary mask and prepare the video. Passing checks records a content fingerprint and returns `ready-for-generation`; continue without asking the user to confirm the mask. Keep the mask, prepared video and numeric report available for optional inspection. Failed checks or visibly incorrect subject coverage still need correction. Changed media or prompt invalidates preparation; rebuild before generation. `approve-review` is optional metadata for reviews the user actually requests or provides, not a prerequisite.
- Generate after validated preparation and paid generation authorization. An existing authorization for the full paid workflow covers generation; do not ask again just because preparation finished. Never switch models, enable draft-ID completion, generate HD, or silently round/trim clips. This package supports whole-second 4–15 second clips, within 85 ms of the target duration.
- Persist request IDs. Poll an existing request instead of resubmitting it. An ambiguous submission blocks further submission until reconciled. A failed job needs explicit retry authorization; use a fresh run rather than overwriting history.

After generation, the helper stream-copies and verifies the first source audio stream, with no `-shortest` truncation. Report additional source audio tracks as not copied. Export the 480p video and request final visual/lip-sync review; packet equality proves audio preservation, not lip sync. Keep paid inference, SAM semantics, and actual CMA acceptance labeled NOT RUN until tested there.
