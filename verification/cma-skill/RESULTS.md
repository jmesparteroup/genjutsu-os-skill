# 30-second clip support — October 12, 2026

PASS: all 20 offline tests with networking disabled in the existing Linux test runtime. Duration boundary coverage accepts 4, 15, 16, 29 and 30 seconds, rejects 3, 4.2, 24.75, 30.1 and 31 seconds, and preserves the 480p non-draft reference payload. The 16, 29 and 30-second cases failed against the old cap before the change. Skill format validation passed.

This update raises the duration guard only; the existing whole-second input requirement remains. No paid inference or 30-second live provider run was performed for this change.

# Automatic mask validation update — October 12, 2026

PASS: all 20 offline tests in the existing Ubuntu 24.04 Linux amd64 Docker runtime, with network disabled and no credentials mounted. The full pipeline uses real media processing and mocked FAL; generation completes without any human review record. New paid requests still require authorization, changed preparation blocks generation, and legacy runs with matching review fingerprints remain usable. Existing binary-mask, color/gray rejection, alignment, audio preservation, retry and two-reference tests pass.

PASS: skill format validation and independent read-only instruction/code review. The baseline test failed at the former `awaiting-human-review` stage before the update, then passed with `ready-for-generation`.

No paid inference or production CMA deployment was performed for this update. Final visual/lip-sync review remains available; automatic mask checks do not prove perfect subject selection. The earlier report below records the previous version's requirements and test scope.

# CMA skill verification — October 11, 2026

PASS: skill format validation; zip integrity; installed-copy equality.
PASS: Ubuntu 24.04 Linux amd64 dependency health (Python 3.12.3, FFmpeg/ffprobe 6.1.1, Rubber Band 3.3.0, fal-client 1.0.3, NumPy 2.2.6).
PASS: real H.264 encode and maskedmerge execution.
PASS: 14 offline tests with network disabled and no mounted credentials. Includes a full staged pipeline with mocked FAL and real media processing, all 96 frames of a four-second mask, overlay/gray/timing rejection, compositing polarity, measured +3-semitone pitch, duration preservation, complete first-source audio packet SHA-256 equality, CMA review/final exports, payment gates, review staleness, resumable request IDs, ambiguous-submission blocking, input mismatch, failed-job blocking, request URL validation and verbatim credential placeholder handling.
PASS: preparation and Seedance payload validation against current public FAL OpenAPI schemas; hashes in schema-check.json.

NOT RUN: upload/attachment in an actual CMA account, CMA vault egress substitution, live FAL uploads/inference, actual SAM video output semantics, human review on a real source clip, final visual/lip-sync acceptance.

No paid inference was submitted. No saved FAL workflows were created or changed. No host system packages were changed. Dependencies were installed only in the owned Docker test image; all test containers used --rm. The original Mac Homebrew FFmpeg remains unmodified.

The package enforces Seedance 2.5 normal generation at 480p and has no HD path. Review records bind content hashes but do not independently authenticate humans; the host must deliver the human confirmation before approve-review. Original audio preservation covers the first source audio stream only.

Artifacts: tests.log, doctor.json, schema-check.json, package-manifest.json and Dockerfile.

Repository packaging verification: all 14 offline tests rerun successfully from the standalone repository skill layout. Skill-format validation and ZIP build passed. The bundle content matches the installed local skill; archive hash reflects the repository ZIP builder.
