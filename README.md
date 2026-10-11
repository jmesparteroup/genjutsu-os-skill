# Genjutsu FAL CMA skill

A reusable skill for Claude Managed Agents that adapts a supplied performance clip to a character reference using FAL. Final generation uses **Seedance 2.5 at 480p**, with a manual full-clip mask review before generation and restoration of the first original audio stream.

The skill includes Linux dependencies, upload/queue orchestration, resumable request IDs, frame-by-frame mask checks, local +3-semitone vocal pitch, compositing, and audio preservation checks. It creates no duplicate saved FAL workflows. Paid inference is disabled by default.

## Install in CMA

**Existing Daimon channel:** import the skill first and preserve its current environment. If dependencies are missing, merge them into a copy of the current environment, preserving its packages and network policy, and test in a dedicated video channel. Selecting an environment affects every conversation in the parent channel. See the [setup and recovery guide](.claude/skills/genjutsu-fal-cma/references/cma-setup.md).

The skill lives at [`.claude/skills/genjutsu-fal-cma`](.claude/skills/genjutsu-fal-cma/SKILL.md), the repository layout CMA discovers when this repository is mounted into a cloud session.

For a new standalone CMA deployment, upload the skill directory through the official Anthropic CLI from a dedicated deployment directory:

```bash
ant apply /absolute/repo/path/.claude/skills/genjutsu-fal-cma
ant apply /absolute/repo/path/.claude/skills/genjutsu-fal-cma/assets/environment.yaml
```

Preserve that deployment directory's `claude-lock.json` privately for later resource updates; it is excluded from this skill source repository. Attach the returned custom skill ID while preserving existing skills, use the validated dedicated environment, and provide FAL credentials through a CMA vault. The standalone template has unrestricted networking; an optional `environment-limited.yaml` explicitly permits MCP servers and package managers. Neither template should replace a shared channel's policy during skill installation. Read the [CMA setup guide](.claude/skills/genjutsu-fal-cma/references/cma-setup.md) and [operation guide](.claude/skills/genjutsu-fal-cma/references/operation.md) for details.

## Build an uploadable ZIP

```bash
python3 scripts/package_skill.py
```

This writes `dist/genjutsu-fal-cma.zip` and its content manifest. It performs no network requests or inference. Generated archives, user media, run state and credentials are excluded from Git.

## Offline verification

The dependency/runtime check and 14 tests passed in Ubuntu 24.04 Linux amd64 with test-container networking disabled. See [the verification record](verification/cma-skill/RESULTS.md).

For the queue/review tests without installing media dependencies:

```bash
python3 verification/cma-skill/test_orchestration.py
```

For all tests and actual local media processing:

```bash
docker build --platform linux/amd64 -f verification/cma-skill/Dockerfile -t genjutsu-fal-cma-test .
docker run --rm --platform linux/amd64 --network none \
  -e GENJUTSU_SKILL_ROOT=/opt/skill genjutsu-fal-cma-test \
  python /opt/skill/scripts/doctor.py
docker run --rm --platform linux/amd64 --network none \
  -e GENJUTSU_SKILL_ROOT=/opt/skill genjutsu-fal-cma-test \
  python -m unittest discover -s /opt/tests -p 'test_*.py' -v
```

Actual CMA deployment, vault egress substitution, live FAL inference, SAM output mask semantics and real-source lip-sync acceptance remain **NOT RUN**. SAM returns a segmentation candidate; the skill requires a usable binary mask and does not assume its video output meets that requirement. Manual approval records bind content hashes but rely on the host to deliver the actual human's confirmation.

This is an adaptation of the [original Genjutsu workflow](https://github.com/sirioberati/Genjustsu-Open-Source-Workflow), not a verified one-click replica. No source clip or character image is included.
