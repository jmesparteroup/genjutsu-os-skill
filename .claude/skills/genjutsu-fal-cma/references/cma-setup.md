# CMA deployment and dependencies

This bundle is self-contained and targets CMA's documented Ubuntu 24.04 x86_64 cloud sandbox. It has no Mac paths and needs no GPU: FAL performs model inference remotely. Local media processing uses FFmpeg/ffprobe, libx264, maskedmerge, Rubber Band CLI, Python 3.10+, `fal-client==1.0.3`, and `numpy==2.2.6`.

## Attach the skill and environment

### Existing Daimon channel

Import and attach the skill while preserving existing skills. Skill installation does not require selecting a new environment. First run the offline dependency check in the current session. If dependencies are missing, inspect the channel's effective environment, save its name/configuration for rollback, and create a separate copy with the required packages merged into its existing package lists. Preserve networking, MCP access, and all other settings. A conflicting Python version needs an isolated environment, not a silent replacement of another workflow's dependency.

Environment selection affects every conversation in the parent channel, not just this skill or thread. Do not select a template for `#general` or change a workspace default merely to install this skill. Use a dedicated video channel when a different runtime is needed. Validate a new environment in that channel before selecting it elsewhere. On Daimon, use `create_environment` with its expected spec shape; the `ant` CLI examples below are for standalone CMA deployments.

### New standalone CMA session

From a dedicated deployment directory with your normal Anthropic account access, upload the unzipped skill using the official `ant` CLI:

```bash
ant apply /absolute/path/to/genjutsu-fal-cma
ant apply /absolute/path/to/genjutsu-fal-cma/assets/environment.yaml
```

Preserve the generated `claude-lock.json` and use that same deployment directory for updates so repeated applies update/version those resources rather than create duplicates. Alternatively, upload `genjutsu-fal-cma.zip` to the Skills API. Skills upload directly to the Skills API, not the Files API. Attach the returned custom skill ID to your existing agent's `skills` array; pin the returned version for deployment. This package does not select or replace your agent's Claude model.

```python
# Fragment to merge into your existing agent/session configuration, not a paid run.
skills = [{"type": "custom", "skill_id": uploaded_skill_id, "version": uploaded_version}]
# Keep the agent's existing skills and enable read + bash in its agent toolset.
# Use the validated dedicated environment_id and vault_ids containing FAL_KEY.
```

Repository-based installation is also supported: place the bundle at the mounted repository root `.claude/skills/genjutsu-fal-cma/`. CMA discovers that exact layout at session start in cloud environments. Do not commit run media, keys or state files with the skill.

`assets/environment.yaml` is a standalone template with unrestricted networking; it is not a replacement for an existing channel's policy. `assets/environment-limited.yaml` is an optional restricted template for a dedicated channel that explicitly needs it. That template enables both package managers and configured MCP servers. In limited mode, `allow_mcp_servers` defaults to false: if an agent's MCP endpoint is outside `allowed_hosts`, CMA can reject session creation with HTTP 400 before the agent can read a repair request. Package-manager access also permits documented code hosts such as GitHub for sandbox commands; general web search/fetch still follows `allowed_hosts`.

The supplied environment installs FFmpeg and Rubber Band using apt, and the two Python dependencies using pip before the agent starts. System package versions follow Ubuntu security updates; Python top-level dependencies are pinned. Always run `python3 scripts/doctor.py` from the discovered skill directory in the actual session: it executes a real H.264 encode with maskedmerge, checks tool executability, and verifies the Python package versions without network calls. Package presence alone is not a passing check.

If configuring environment packages is unavailable, an explicitly invoked Linux-only fallback exists:

```bash
bash /absolute/skill/path/scripts/bootstrap.sh --install /workspace/.venvs/genjutsu-fal-cma
```

It requires root inside the owned Linux container for apt and installs Python dependencies into an isolated venv. Then use that venv's Python for all scripts. Do not use it to change host system packages or repair Homebrew. Self-hosted CMA workers can build the same dependencies into their own image; the environment `packages` block is for cloud environments.

## FAL credentials

For cloud CMA, create/reuse a vault credential with `auth.type=environment_variable`, `secret_name=FAL_KEY`, header injection enabled, and these credential substitution hosts:

- `queue.fal.run`
- `rest.alpha.fal.ai`

Supply the secret privately through your host's secret management or Claude Console. Reference the vault in `vault_ids` at session creation. Do not place the key in agent prompts, skill files, workflow inputs, shell arguments, JSON state or `.env` inside this bundle. The environment variable appears as an opaque placeholder inside CMA and is replaced at outbound egress. The queue client sends it unchanged in `Authorization: Key …`; the pinned FAL upload client's auth source also uses that value verbatim. This compatibility is source-inspected, not live-tested through CMA's egress proxy. FAL CDN upload tokens returned by the service are handled transiently by the SDK and not saved by this tool.

Environment-level networking and credential-level substitution both need to permit the destination. The optional limited environment includes FAL API/queue/CDN hosts and `storage.googleapis.com` for model output URLs, plus configured MCP endpoints and package-manager hosts. If an output URL uses another domain under a limited policy, add the exact legitimate host after inspection; do not automatically broaden egress. If upload auth requests move from `rest.alpha.fal.ai`, inspect the pinned client and adjust the credential host explicitly.

Self-hosted CMA does not currently support vault `environment_variable` credentials. Inject `FAL_KEY` privately into the worker container using your infrastructure's secret mechanism instead. Enable outbound access to the same APIs/CDNs.

## Inputs, outputs and review

Attach source media and character images as CMA session file resources, with absolute paths such as `/workspace/input/source.mp4`. They are read-only; the script copies them to a fresh writable `/workspace/genjutsu-runs/<name>` directory. Write review/final exports to `/mnt/session/outputs` with the `export` command. The CMA host can retrieve those through the session-scoped Files API and present them to the reviewer. Passing automatic preparation checks permits generation when paid execution is authorized. Mask confirmation is optional; the host should not pause for it. Use `approve-review` only to annotate an actual optional human review.

No skill installation or environment creation authorizes paid inference. Begin with `doctor`, `init`, and a plan. Preserve the user's no-inference constraint until explicitly lifted.

## Recover a Daimon channel that cannot start

“I could not get ... ready with the latest setup” is a preparation failure, not a model reply. Repeated requests in that conversation cannot repair a session that never starts. The message alone does not establish the underlying error; check backend `session_preparation.failed` / `session_preparation.update_failed` logs for the exact cause.

1. In the affected parent Discord channel, an authorized admin can run `/agent-setup`, open **Who answers where**, and use **Environment for #<channel>** to restore the recorded previous environment. Choose **Use the default (...)** only if the channel previously inherited that known working default. The setup panel runs outside the agent session.
2. If the deployed panel lacks the selector, use an authenticated external admin/operator MCP client or a working channel to call `set_channel_environment` with the previous environment and explicit affected `channel_id`; use `clear_channel_environment(channel_id=...)` only when restoring inheritance. Omitting `channel_id` changes the workspace default. Honor any existing access-policy confirmation requirement; do not bypass it through database edits.
3. Send a new message in the original conversation to check that startup succeeds. Preserve the conversation and working files; do not delete sessions, keys, or skills as a network repair. If it still fails, inspect the preparation exception before changing anything else.
4. Once working, run `scripts/doctor.py` offline. Reimporting a newer skill version or updating this repository does not update a saved CMA environment or Daimon's channel selection. Repair those explicitly through the host's administration path. Keep paid inference disabled throughout recovery.

## Evidence and references

The package is tested locally with offline synthetic media and mocked FAL responses in an Ubuntu 24.04 amd64 container. Actual CMA mounting, egress placeholder substitution, FAL inference, SAM mask semantics, and real-source lip-sync acceptance still require live validation. No official runtime equivalence is claimed.

- [CMA skills and uploads](https://platform.claude.com/docs/en/managed-agents/skills)
- [CMA environment packages and networking](https://platform.claude.com/docs/en/managed-agents/environments)
- [CMA sandbox reference](https://platform.claude.com/docs/en/managed-agents/cloud-sandboxes-reference)
- [CMA vault environment credentials](https://platform.claude.com/docs/en/managed-agents/vaults)
- [FAL asynchronous queue](https://fal.ai/docs/documentation/model-apis/inference/queue)
- [Demucs](https://fal.ai/models/fal-ai/demucs/api)
- [Video Depth Anything](https://fal.ai/models/fal-ai/depth-anything-video/api)
- [SAM 3 video-rle](https://fal.ai/models/fal-ai/sam-3/video-rle/api)
- [Seedance 2.5](https://fal.ai/models/bytedance/seedance-2.5/reference-to-video/api)
