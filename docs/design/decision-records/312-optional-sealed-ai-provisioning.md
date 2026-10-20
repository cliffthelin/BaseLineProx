# DR312 — Optional preboot AI credentials, native configuration and MCP setup

Date: 2026-10-19. Direct operator request supersedes the queue's older exclusion
of provider configuration forms. This is an opt-in installer feature for new
builds, updates and rebuilds, alongside DR311's Bluetooth choice.

## Storage, interface and execution

Installer **Parent settings → AI providers, credentials and MCP setup** opens
`/ai-setup/installer`. The choices are off, import the selected parent setup, or
prepare custom settings. The catalog includes OpenAI API, Codex, ChatGPT, Gemini,
Antigravity, Claude Code CLI, Claude Desktop, OpenCode, OpenRouter, Ollama,
LM Studio, Muse, Grokbot and DeepSeekHarness. It extends the configuration catalog,
not the executable harness registry: unsupported native harness adapters are not
advertised as implemented. Muse/Grokbot/DeepSeekHarness accept custom settings;
their exact application identities/native adapters remain an explicit question.

The saved plan's `host_configuration.ai_setup` contains mode, selected provider
IDs, target grants, the `AI_SETUP_DEFAULT` vault reference and, for newly prepared
profiles, a SHA256 of the encrypted profile. Inline profile/credential fields are
refused by draft storage and input-bundle preparation. A changed sealed profile
invalidates the captured choice rather than silently applying new credentials.

The native auth/config files and custom environment/MCP settings live in an
ENC1-sealed USER_ADMIN vault entry, using the existing passphrase and cipher.
The agent never imports or inspects the operator's credentials. The application's
explicit parent importer reads only the selected supported files, checks bounded
regular files and refuses symlinks. Discovery returns presence/counts/names only.
Custom tokens are entered directly in the app (masked API/setup-token input),
never through agent chat or into a configuration draft. A prepared profile is not
an authentication-success claim.

On an installed parent the vault is on mounted USER_ADMIN. On this build host,
preboot encrypted staging is on CACHE at
`baseline-build/parent-user-admin/vault`, with a separate personal staging root.
No new fallback writes an unmounted USER_ADMIN folder on the development root.
The generic vault page uses these same roots. Existing explicitly configured
embedding/test roots remain supported. The obsolete vault module docstring
claiming encryption was not built has been corrected.

Offline executors copy sealed bytes only, into the child's USER_ADMIN vault,
plus `ai-setup.json` with its grants. A new child inherits the source verifier;
a different existing child vault requires human unlock/resealing instead of an
automatic replacement. Child data is not formatted. The web updater, rebuild
`--plan FILE`, and allscript fresh-build/update paths consume the choice. Fresh
allscript builds apply it after clean install-VM shutdown. As in DR311, general
new-install execution from the web page is still not built; exported plans are
consumed by the allscript path. The encrypted profile is an external input,
not embedded in the source/installer cache.

## Host, VM, container and workspace access

The permitted places are Proxmox substrate tools, BaselineOS tools, managed VMs,
managed LXC containers, and the Kasm server/workspaces. Explicit targets and
wildcard grants are validated. The legacy turnkey “grant all vault names” path
excludes `AI_SETUP_DEFAULT`, so it cannot override these choices.

After vault unlock, `baseline-ai-sync.timer` retries delivery every 30 seconds.
The status file on USER_ADMIN records delivered targets, pending targets,
inventory errors or locked state. It does not run a provider request or execute
MCP server commands. Stopped, missing, incompatible or unavailable targets remain
pending. The app also offers explicit activation/delivery.

Host clients and `baseline-ai-run PROVIDER -- PROGRAM` use a private per-account
RAM profile and per-client HOME. Codex, Claude Code and OpenCode harness subprocesses
receive that environment without changing the parent process's HOME. The native
client parses its own copied auth/MCP configuration. Selected common API settings
can supply Codex/OpenCode; conflicting endpoints/keys require explicit settings.
Availability remains “configured, not live checked.”

Guest delivery uses stdin, never command-line credential values. Managed VM
execution retains existing storage/ownership/guest-agent guards. The new LXC
`guest_exec` uses the container's managed identity checks before `pct exec`.
Kasm delivery checks both the host command and guest exit status; workspace
inventory identifies containers with the Kasm user's HOME, and workspace delivery
checks `/dockerstartup` before `docker exec`. These are native code paths, not
physical-runtime verification. Python and the desired clients must be present;
missing prerequisites are errors, not empty success. Guest account selection
prefers the managed UID 1100, then `kasm-user`, then a unique interactive user;
root-only containers use root. Ambiguity requires an explicit account.

Plaintext stays in private `/run` files and client subprocess environments.
Locking the host vault clears host AI runtime copies. Already delivered remote
copies last until that target stops/reboots; locking does not revoke a provider
token at its issuer. Native client token refreshes remain in RAM; re-import/reseal
is required to persist changed native auth/config files for a future boot.

## Limits and source evidence

This feature does not install every client or model, port arbitrary project paths,
reconfigure a parent's loopback endpoint for a guest, or clone OS keyrings/browser
sessions. The catalog notices retain those distinctions. Copied OAuth credentials
may still need provider reauthorization. No operator token was entered, viewed,
logged, tested or migrated by the agent. No paid API call was made.

Native paths and credential boundaries were checked against:

- [OpenAI authentication](https://developers.openai.com/codex/auth/) — file cache
  versus OS credential storage and supported headless cache transfer.
- [Codex MCP](https://developers.openai.com/codex/mcp/) — native TOML configuration.
- [Claude Code MCP](https://code.claude.com/docs/en/mcp) — user configuration in
  `.claude.json`, distinct from project-scoped configuration.
- [OpenCode configuration](https://docs.opencode.ai/docs/config/) — native JSON/JSONC
  provider and MCP settings.
- [Gemini CLI authentication](https://geminicli.com/docs/get-started/authentication/)
  and [Antigravity MCP](https://antigravity.google/docs/mcp).
- [Kasm workspace configuration](https://docs.kasm.com/docs/how-to/workspaces-sessions/container-workspace/workspaces/)
  for workspace/container setup boundaries.

## Verification and remaining acceptance

The focused source/unit set passed 347 checks before the final presence-status
addition; final check results are recorded in verification/312/README.md.
Evidence includes real encryption/temp files, real local HTTP/draft storage,
a real launcher subprocess with a synthetic key, and injected native target
transport tests. Actual Chromium proved the full catalog, masked custom-key save,
sealed-at-rest storage, reference-only drafts, reload retention and opt-out using
synthetic credentials/drives. Screenshot: `docs/verification/312/installer-ai-setup.png`.
No provider account authentication, native Proxmox boot, real LXC delivery or
real Kasm workspace delivery was verified. No QEMU run was performed here.

Physical code deployment is pending desktop authentication at this checkpoint.
The prepared code-only helper is `/tmp/baseline-ai-feature-deploy.py`; it validates
PC601 by serial, source role UUID and SUBSTRATE policy, and the mirror by UUID and
its child's volume manifest. It preserves unrelated deployed web work through
function/route insertion rather than copying the entire concurrent web module.
It backs up changed code on CACHE, installs/enables the retry timer offline,
compares bytes and unmounts. It never reads or imports a real AI profile.

Queue72/76 retains the general web new-build executor; queue72/78 retains native
boot, provider sign-in and guest/workspace acceptance. Native adapter identification
for Muse/Grokbot/DeepSeekHarness and durable native-token-refresh capture remain
explicit follow-ups. INSTALL and the queue were updated; DR258 and DR311 remain
history. This record supersedes the provider-form exclusion, not prior proof limits.
