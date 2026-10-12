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
