# Environment setup correction — 2026-10-12

The original limited-network template omitted `allow_mcp_servers`. Anthropic's environment documentation states that it defaults to false and session creation fails with HTTP 400 when an agent declares an MCP host outside `allowed_hosts`. This explains a possible startup failure before an agent can process repair instructions; it is not a confirmed production incident diagnosis without logs.

Correction:
- The standalone template uses unrestricted networking, for new dedicated sessions only.
- A separate optional limited template explicitly permits configured MCP servers and package managers.
- Existing Daimon installs preserve their effective environment and merge missing dependencies into a separate copy. They do not replace shared channel/workspace settings during skill installation.
- The setup reference documents recovery through the Discord admin panel or an authenticated external control path. Publishing a skill update does not modify existing saved environments.

Verification performed without inference:
- Before correction, parsing the original YAML and checking MCP compatibility failed: limited networking did not permit configured MCP servers.
- Both updated YAML templates parsed successfully and passed MCP/package-access and pinned-dependency checks.
- Skill frontmatter validator passed.
- All 11 offline queue/review orchestration tests passed, including 480p, paid-request gating and stale-review rejection.
- Upload ZIP rebuilt and its integrity checked by `scripts/package_skill.py`.
- `git diff --check` passed.

No live environment mutation, source upload, FAL inference or CMA startup validation was performed for this correction. The original full offline media verification is recorded separately in RESULTS.md.

Reference: https://platform.claude.com/docs/en/managed-agents/environments (checked 2026-10-12).
