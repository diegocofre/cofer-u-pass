# Cofer U Pass v1 — Operational Runbook

This runbook is the operational source of truth for Cofer U Pass 1.0.x. v1 is a local, single-OS-user service. It is not designed for remote exposure, shared profiles, or multi-user operation.

## 1. Supported platforms and prerequisites

Supported baseline: Python 3.11–3.13, Windows 10/11, and mainstream x86_64 Linux distributions. Chromium is the build managed by Playwright; system Chrome/Edge is not used.

Preconditions: Python is available and either `uv` or `pipx` is installed.

Bash:

```bash
python --version
uv --version || pipx --version
```

PowerShell:

```powershell
python --version
uv --version
# or
pipx --version
```

Expected: a supported Python version and one tool manager. Recovery: install Python and `uv`/`pipx`; do not use administrator/root privileges solely for Cofer U Pass.

## 2. Installation with uv tool and pipx

Bash:

```bash
uv tool install cofer-u-pass==1.0.0
# or
pipx install cofer-u-pass==1.0.0
```

PowerShell:

```powershell
uv tool install cofer-u-pass==1.0.0
# or
pipx install cofer-u-pass==1.0.0
```

Expected: `cofer-u-pass --help` and `cofer-u-pass --version` work. Recovery: reinstall the same pinned version. Prereleases may be installed explicitly with `uv tool install --prerelease allow cofer-u-pass` or the corresponding pipx/pip command.

Verify the package selected by your shell:

Bash:

```bash
which cofer-u-pass
cofer-u-pass --version
```

PowerShell:

```powershell
Get-Command cofer-u-pass
cofer-u-pass --version
```

Expected: the executable path and installed package version are the ones intended for this environment. This is especially important when a project virtual environment and a `uv tool` installation coexist.

## 3. Setup, directories, and permissions

Inspect changes first:

Bash:

```bash
cofer-u-pass setup --dry-run
cofer-u-pass setup
```

PowerShell:

```powershell
cofer-u-pass setup --dry-run
cofer-u-pass setup
```

`setup` creates the config file, data root, `profiles/`, `artifacts/`, `evidence/`, `backups/`, `logs/`, `tmp/`, `secrets/api-token`, SQLite database, and Playwright Chromium. On Linux, private directories are mode `0700` and the token is mode `0600`.

Expected: setup reports `status: ok`; `cofer-u-pass doctor` passes. Warning: `--skip-browser` is only for offline/advanced cases and leaves the runtime unusable until Chromium is installed. Recovery: rerun `setup`; it is idempotent and does not delete profiles, runs, artifacts, or user configuration.

## 4. Complete TOML configuration reference

Canonical configuration is TOML. Obtain the actual path with `cofer-u-pass config paths`.

```toml
schema_version = "1.0"
data_root = "/user-specific/data/root"
log_level = "INFO"

[browser]
global_concurrency = 2
headless_default = false

> Headless execution is adapter-gated. Since v1.0.2, the official ChatGPT, Gemini, and DeepSeek adapters remain visible-only until supervised provider smoke tests demonstrate reliable headless authentication and execution. `profiles status --verify` follows the adapter's authentication-verification policy rather than forcing headless mode.
action_timeout_seconds = 90.0
response_stability_seconds = 1.5

[api]
host = "127.0.0.1"
port = 8765
token_file = "secrets/api-token"
cors_origins = []

[security]
max_input_file_bytes = 104857600
max_artifact_bytes = 524288000
allowed_input_extensions = []
allowed_artifact_extensions = []

[retention]
events_days = 30
evidence_days = 30
backups_days = 30
artifacts_days = 90
completed_runs_days = 90

[hooks]
timeout_seconds = 60.0
max_input_bytes = 2097152
max_output_bytes = 2097152

[doctor]
screenshots = false
dom_fragments = true
network_diagnostics = false
```

Security constraint: `api.host` must remain `127.0.0.1`, `::1`, or `localhost`; there is no v1 remote-bind mode. Empty extension allowlists mean “no extension restriction”; size limits still apply.

Validate after editing:

Bash:

```bash
cofer-u-pass config validate
cofer-u-pass config show --effective
```

PowerShell:

```powershell
cofer-u-pass config validate
cofer-u-pass config show --effective
```

Expected: schema validation succeeds and secrets are not printed. Recovery: restore the last known-good TOML or rerun `setup` after moving the broken config aside.

## 5. Environment variables and precedence

Precedence is explicit options, documented environment variables, profile settings, global TOML, then secure defaults.

Documented v1 variables:

- `COFER_U_PASS_CONFIG`
- `COFER_U_PASS_DATA_ROOT`
- `COFER_U_PASS_LOG_LEVEL`
- `COFER_U_PASS_API_PORT`
- `COFER_U_PASS_BROWSER_CONCURRENCY`
- `COFER_U_PASS_HEADLESS`

Bash example:

```bash
export COFER_U_PASS_LOG_LEVEL=DEBUG
cofer-u-pass config show --effective
```

PowerShell:

```powershell
$env:COFER_U_PASS_LOG_LEVEL = "DEBUG"
cofer-u-pass config show --effective
```

Expected: effective configuration reflects the override. Warning: security-global values such as remote API binding are not opened by environment override. Recovery: unset the variable.

## 6. Profile creation, authentication, inspection, and maintenance

Create one profile per provider/account context.

Bash:

```bash
cofer-u-pass profiles create personal-chatgpt --provider chatgpt
cofer-u-pass profiles authenticate personal-chatgpt
cofer-u-pass profiles status personal-chatgpt --verify
```

PowerShell:

```powershell
cofer-u-pass profiles create personal-chatgpt --provider chatgpt
cofer-u-pass profiles authenticate personal-chatgpt
cofer-u-pass profiles status personal-chatgpt --verify
```

Authentication opens visible managed Chromium. Complete password, MFA, CAPTCHA, consent, and verification yourself. Cofer U Pass only recognizes the authenticated application state.

Expected: status becomes `ready` and `authenticated: true`. Warning: never copy profile contents into tickets/diagnostics. Recovery: rerun `profiles authenticate`; do not delete/rebuild a profile automatically after a crash—run Doctor first.

## 7. CLI execution

Example:

Bash:

```bash
cofer-u-pass run examples/ask.yaml \
  --profile personal-chatgpt \
  --input prompt='Explain event sourcing in five sentences.'
```

PowerShell:

```powershell
cofer-u-pass run examples/ask.yaml `
  --profile personal-chatgpt `
  --input 'prompt=Explain event sourcing in five sentences.'
```

Expected: lifecycle events are printed, followed by the final run/result document. `--json` emits machine-readable JSON/event lines.

Warning: a CLI foreground run owns the browser for that profile until it reaches a safe terminal state. Recovery: Ctrl+C initiates process shutdown; the next process startup classifies an interrupted effect conservatively.

### Interactive terminal chat

Bash / Git Bash:

```bash
cofer-u-pass chat --profile personal-chatgpt
```

PowerShell:

```powershell
cofer-u-pass chat --profile personal-chatgpt
```

To resume a known Cofer U Pass conversation:

```bash
cofer-u-pass chat --profile personal-chatgpt --conversation-id <conversation-id>
```

Expected result: the terminal shows `You>` and `Assistant>` prompts without the verbose run JSON. `/id` displays the persisted conversation id, `/new` makes the next message create a new provider conversation, and `/exit` ends the local chat session. Each message remains a separate immutable run and therefore retains normal checkpoints, failure classification, and recovery semantics.

Warning: v1 provider adapters may require visible Chromium, so a browser window can open for every chat turn. This command intentionally does not introduce a long-lived browser session outside the run lifecycle. Recovery: if a turn ends as `authentication_required`, `recoverable`, or `outcome_unknown`, chat stops before accepting another message so that the run can be resolved safely.

## 8. Python library usage

```python
import asyncio
from cofer_u_pass import CoferUPass

async def main():
    async with CoferUPass() as cup:
        handle = await cup.run(
            "examples/ask.yaml",
            profile="personal-chatgpt",
            inputs={"prompt": "Explain event sourcing in five sentences."},
        )
        async for event in handle.events():
            print(event.type, event.sequence)
        run = await handle.wait()
        print(run.state)
        print(await handle.result())

asyncio.run(main())
```

Expected: `run()` returns a `RunHandle` immediately; the handle provides state, event iteration, wait, cancel, resume, result, and artifacts. Recovery: persist `run_id`; a later process can obtain a new handle with `await cup.get_run(run_id)`.

## 9. HTTP API and SSE usage

Start the foreground API:

Bash:

```bash
cofer-u-pass serve
TOKEN="$(cat "$(cofer-u-pass config paths | python -c 'import json,sys; print(json.load(sys.stdin)["data_root"] + "/secrets/api-token")')")"
```

PowerShell:

```powershell
cofer-u-pass serve
# In another shell, use `cofer-u-pass config paths` to locate data_root,
# then read secrets\api-token with Get-Content.
```

Create a run with any HTTP client using `Authorization: Bearer <token>` and JSON body containing `protocol_path`, `profile_id`, `inputs`, and optional conversation/idempotency fields.

SSE endpoint: `GET /api/v1/runs/{run_id}/events`. Reconnect using the exact last received `event_id` in `Last-Event-ID`.

Expected: API remains on loopback and events resume in monotonic sequence order. Warning: never put the bearer token in a URL/query string. Recovery: if the token is compromised, stop the service, run `cofer-u-pass config rotate-token`, then restart it. The token value is not printed.

## 10. Foreground and optional user-level service operation

Primary operation:

Bash/PowerShell:

```text
cofer-u-pass serve
```

First interrupt stops new work, preserves queued runs, requests safe cancellation for active runs, closes Chromium, and releases locks through FastAPI lifespan shutdown. A forced second termination may prevent cooperative cleanup; subsequent startup uses journal recovery.

Linux optional background operation should use `systemd --user`; Windows may use Task Scheduler under the same user account. Do not install a privileged system service and do not expose the loopback port remotely.

Recovery after forced exit: run `cofer-u-pass doctor`, inspect profile locks/leases, then `cofer-u-pass status <RUN_ID>`.

## 11. Protocols, hooks, and adapters

Validate protocol behavior by running deterministic tests. Protocols may not contain selectors, arbitrary JS/Python, shell commands, unrestricted URLs, or provider-derived actions.

Hooks use trusted `module:function` references and JSON input/output contracts. They execute in a separate process with reduced environment and limits, but are not a hostile-code sandbox.

Adapters live under `cofer_u_pass.adapters.<provider>` with `rules.json`. Provider repairs must add/update sanitized fixtures and regression tests before activation.

Expected: a protocol declares only logical operations/capabilities. Recovery: a missing capability fails preflight before the provider conversation is modified.

## 12. Artifacts, logs, and evidence

Artifacts are stored below `artifacts/<run_id>/`, receive UUID-prefixed safe names, SHA-256, size, MIME metadata, source, run, and action identity. Files are copied through a temporary file and atomically renamed.

Diagnostics are below `evidence/<run_id>/<package_id>/`.

Bash/PowerShell:

```text
cofer-u-pass doctor --run-id <RUN_ID>
cofer-u-pass diagnostics inventory <PACKAGE_DIR>
```

Expected: inventory contains only sanitized JSON/manifest files unless future browser evidence is explicitly captured. Warning: review inventory before sharing. Recovery: diagnostic capture failures do not change run outcome.

## 13. Backups, migrations, and rollback

Before package update:

Bash/PowerShell:

```text
cofer-u-pass update --check
cofer-u-pass update
```

The update path refuses active runs, performs SQLite integrity validation, and creates a timestamped backup before invoking `uv tool upgrade` or `pipx upgrade`.

Rollback example:

Bash:

```bash
uv tool install --force cofer-u-pass==1.0.0
```

PowerShell:

```powershell
uv tool install --force cofer-u-pass==1.0.0
```

If the older package cannot read a future schema, stop the service and restore the matching SQLite backup. Warning: do not attempt an uncertain reverse migration.

## 14. Cancellation, resume, and reconciliation

Cancel:

```text
cofer-u-pass cancel <RUN_ID>
```

A running run becomes `cancelling`; no new action starts and the active action reaches a safe boundary when possible. It then becomes `cancelled`, `recoverable`, or `outcome_unknown`.

Resume:

```text
cofer-u-pass resume <RUN_ID>
```

Direct resume is allowed for `recoverable` and `authentication_required` after authentication is restored. Resume reopens the profile/conversation and reconciles the latest checkpoint; it does not blindly continue from the stored index.

Expected: confirmed actions are not repeated. Recovery: if reconciliation cannot establish safety, stop and investigate `outcome_unknown` rather than forcing a retry.

## 15. Lock and interrupted-process recovery

The profile directory contains the authoritative OS lock. SQLite contains a lease/heartbeat for observability.

Run:

```text
cofer-u-pass doctor
cofer-u-pass profiles status <PROFILE>
```

Expected: a profile is operated by only one process. A new process clears stale SQLite leases only during conservative startup recovery; it does not bypass an active OS lock.

Warning: never manually delete a lock file merely because it exists; the file itself is not proof that the OS lock is active. Recovery: stop residual Chromium/Cofer U Pass processes owned by your user, then rerun Doctor.

## 16. `authentication_required` recovery

```text
cofer-u-pass profiles authenticate <PROFILE>
cofer-u-pass profiles status <PROFILE> --verify
cofer-u-pass resume <RUN_ID>
```

Expected: run state is preserved while authentication is restored manually. No automatic login is attempted. Recovery: if the provider shows an unknown verification screen, leave the run paused and inspect diagnostics/adapter compatibility.

## 17. `outcome_unknown` investigation and resolution

First inspect the run/action journal and provider conversation manually. Do not send the message/file again until you know whether the effect happened.

If the effect definitely occurred:

```text
cofer-u-pass resolve-outcome <RUN_ID> --action <ACTION_ID> --effect occurred
```

If it definitely did not occur:

```text
cofer-u-pass resolve-outcome <RUN_ID> --action <ACTION_ID> --effect not-occurred
```

Expected: the manual resolution is persisted as evidence and the run is queued for reconciliation/resume. Warning: this is an explicit human safety decision. If uncertain, leave the run `outcome_unknown`.

## 18. Preventive and reactive Doctor usage

Preventive:

```text
cofer-u-pass doctor
```

Checks Python, loopback API configuration, filesystem access, SQLite integrity/schema, disk space, managed Chromium, leases, profiles, and adapter/rule loading.

Reactive:

```text
cofer-u-pass doctor --run-id <RUN_ID>
cofer-u-pass diagnostics inventory <PACKAGE_DIR>
cofer-u-pass diagnostics export <PACKAGE_DIR> --output diagnostic.zip
```

Expected: sanitized evidence package plus manifest/hashes. Warning: inventory review is required before sharing. There is no automatic upload.

## 19. Provider smoke tests

Live ChatGPT, Gemini, and DeepSeek smoke tests are supervised and never run in CI.

Preconditions: manually authenticated dedicated test profiles, provider terms/account rules understood, no sensitive test content.

Bash:

```bash
COFER_U_PASS_SMOKE_PROFILE=personal-chatgpt \
COFER_U_PASS_SMOKE_PROVIDER=chatgpt \
pytest -m smoke tests/smoke
```

PowerShell:

```powershell
$env:COFER_U_PASS_SMOKE_PROFILE = "personal-chatgpt"
$env:COFER_U_PASS_SMOKE_PROVIDER = "chatgpt"
pytest -m smoke tests/smoke
```

Expected: affected provider flow passes under human supervision. Recovery: on UI mismatch, preserve the stable adapter, generate sanitized evidence, repair in isolation, add a regression fixture, and release only after review.

## 20. Updates, prereleases, and version pinning

Check only:

```text
cofer-u-pass update --check
```

Apply through the detected tool manager:

```text
cofer-u-pass update
```

Pin explicitly when reproducibility matters:

```text
uv tool install --force cofer-u-pass==1.0.0
```

Expected: no component silently updates during a run. Warning: live provider compatibility can change independently of package version; supervised smoke validation is part of release acceptance.

## 21. Retention, cleanup, and uninstall

v1 exposes explicit, conservative retention cleanup. Preview first:

```text
cofer-u-pass cleanup
```

Apply only after reviewing the plan:

```text
cofer-u-pass cleanup --apply
```

Cleanup refuses queued/running/cancelling runs, never removes profiles or imported conversations, preserves unresolved incident evidence, keeps artifacts for retained runs, and always protects the three newest SQLite backups.

Uninstall package only:

Bash/PowerShell:

```text
uv tool uninstall cofer-u-pass
# or
pipx uninstall cofer-u-pass
```

This does not intentionally delete the data root. Warning: deleting the data root destroys authenticated profiles, execution history, artifacts, backups, and the API token. Recovery is possible only from your own filesystem/disk backups.

## 22. Troubleshooting by symptom

| Symptom | Likely cause | Verified command / recovery |
| --- | --- | --- |
| `Chromium` Doctor check fails | Browser not installed for Playwright package | `cofer-u-pass setup` |
| Profile says `authentication_required` | Session expired or provider verification | `cofer-u-pass profiles authenticate <PROFILE>` then resume |
| Run remains `queued` | Same profile busy or global concurrency reached | `cofer-u-pass status <RUN_ID>` and `cofer-u-pass doctor` |
| Run becomes `adapter_mismatch`/failed | Provider DOM no longer matches rules | `cofer-u-pass doctor --run-id <RUN_ID>`; inspect sanitized package |
| Run becomes `outcome_unknown` | Possible external effect not confirmed | Inspect provider manually; use `resolve-outcome` only with certainty |
| API returns 401 | Missing/incorrect bearer token | Read configured token file; do not pass token in URL |
| API refuses non-loopback host | v1 security policy | Use `127.0.0.1`/`::1`; remote exposure is unsupported |
| SQLite integrity fails | Storage/process problem | Stop service, preserve DB, restore validated backup; do not migrate |
| Profile locked after crash | Residual process or real concurrent user process | Stop residual user processes; rerun Doctor; do not blindly delete lock |
| Attachment rejected before browser action | Missing file, size/type policy, symlink | Fix input path/policy; preflight has not modified provider conversation |

For unresolved incidents, preserve `run_id`, exact package version, platform, sanitized Doctor package, and reproduction protocol. Do not attach browser profiles or tokens.
