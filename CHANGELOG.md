# Changelog

## 1.2.0 - 2026-07-28

- Separate authenticated browser profiles from public inference identity: restricted provider requests now use discovered provider `model` ids plus optional `reasoning.effort`.
- Add provider-neutral inference domain types and first-class `configure_inference` execution actions.
- Enforce verified inference configuration before `send_message`; unsupported or unverifiable model/effort selections fail closed without silent fallback.
- Implement dynamic ChatGPT Web model discovery, intelligence/effort discovery, model selection, effort selection, and effective-state verification.
- Add normalized public effort support for `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, and `max`, while retaining provider-native labels in evidence.
- Add a rebuildable per-profile model catalog outside authoritative SQLite state, with explicit refresh and stale/error handling.
- Change `/v1/models` to advertise discovered provider models and effort metadata rather than browser profile ids.
- Retain the v1.1 profile-id-as-model form temporarily as an unadvertised legacy alias when no `reasoning.effort` is requested.
- Extend worker registration additively with profile model catalogs and reasoning-effort metadata while preserving profile-based leasing fields.
- Add `cofer-u-pass profiles models PROFILE [--refresh]` for catalog inspection and rediscovery; CLI authentication performs a best-effort post-auth catalog refresh.
- Add deterministic inference contract tests, controlled Chromium ChatGPT picker tests, worker/catalog/API regression coverage, and a supervised ChatGPT model+effort smoke gate.
- Add the model catalog/manual validation runbook and update provider/compatibility documentation for Stage 1.

## 1.1.0 - 2026-07-28

- Add restricted OpenAI-compatible provider mode for authenticated web profiles through `/v1/responses` and `/v1/files`.
- Add `cofer-u-pass.exchange/1`, a minimal per-request protocol that controls input transport and expected text/file/bundle output without encoding task roles or templates.
- Explicitly reject `tools`, `tool_choice`, and function-calling semantics for web models.
- Add safe ZIP input normalization with traversal, symlink, nested-archive, entry-count, expanded-size, and depth protections.
- Add provider-generated artifact and ZIP validation, including required bundle-member checks.
- Add a persistent provider file store for files uploaded before a run.
- Add `cofer-u-pass worker` for an outbound, authenticated connection to a Cofer One IA bridge; browser profiles and cookies remain local to the host.
- Stream bridge input/output files in bounded chunks and keep worker heartbeats alive during long web tasks.
- Expand ChatGPT artifact locators for downloadable sandbox/backend file links.
- Add provider/file/exchange/worker/API regression coverage.
- Remove stale committed 1.0.6 build artifacts; v1.1 release wheel/sdist are built and validated from source instead of leaving mismatched binaries in the tree.

## 1.0.6 - 2026-07-27

- Add `cofer-u-pass chat --profile PROFILE`, a clean interactive terminal façade over ordinary persisted runs.
- Keep each user turn as an immutable run and continue through the persisted `conversation_id`; `/new` starts a fresh provider conversation without introducing a parallel execution engine.
- Add `/id`, `/help`, `/new`, and `/exit` interactive commands.
- Hide run/action/event JSON during chat and print only the canonical assistant Markdown plus actionable terminal-state failures.
- Refactor CLI run waiting through a shared cleanup-aware helper so `run` and `chat` preserve the same executor cleanup barrier.
- Add CLI regression coverage for conversation reuse and `/new`.

## 1.0.5 - 2026-07-26

- Fix canonical plain-text rendering so container fallback text is not concatenated with child text representing the same DOM content.
- Preserve inline child order for paragraph plain-text rendering.
- Add regression coverage based on the first successful live ChatGPT end-to-end run, where `COFER-U-PASS-OK` was previously emitted twice in `result.text`.

## 1.0.4 - 2026-07-26

- Centralize bounded authentication polling in the adapter contract via `wait_until_authenticated()`.
- Fix run preflight false `authentication_required` results when a provider's authenticated shell mounts after `DOMContentLoaded`.
- Make interactive authentication, status verification, run preflight, and conversation operations share the same authentication semantics.
- Make the CLI wait for executor cleanup before leaving a terminal run state, preventing Playwright subprocess transports from being torn down with the asyncio loop on Windows/Python 3.13.
- Add `cofer-u-pass --version`.
- Add regression coverage for delayed run authentication, cleanup barriers, and the root version option.

## 1.0.3 - 2026-07-26

- Fixed a live ChatGPT verification race: `profiles status --verify` now waits for the authenticated application shell to mount instead of performing a single immediate check after `DOMContentLoaded`.
- Preserves the v1.0.2 visible verification policy for ChatGPT, Gemini, and DeepSeek.
- Added regression coverage for delayed authenticated UI mounting.

## 1.0.2 - 2026-07-26

- Fix `profiles status --verify` false negatives for providers whose authenticated UI is not reliable in Playwright headless mode.
- Add explicit adapter manifest flags for headless execution and headless authentication verification.
- Keep ChatGPT, Gemini, and DeepSeek visible-only until supervised headless compatibility is demonstrated; the controlled `generic` adapter remains headless-capable.
- Fix Windows profile-lock contention so an occupied mandatory byte lock is reported as a busy profile instead of raising `PermissionError` while reading the lock file.
- Add regression coverage for verification-mode selection and Windows lock contention.

## 1.0.1 - 2026-07-26

- Fix ChatGPT manual authentication closing immediately when the anonymous composer is visible.
- Add optional `unauthenticated` adapter rules so explicit login/signup UI overrides weak positive authentication signals.
- Add regression tests for authenticated-state precedence.

## 1.0.0 - 2026-07-26

Initial public v1 implementation.

- Shared async application service behind Python, CLI, and HTTP/SSE interfaces.
- Versioned protocol, event, block, adapter-rule, run, and configuration schemas.
- SQLite WAL persistence, immutable plans, actions, events, checkpoints, leases, backups, and conservative restart recovery.
- Playwright-managed Chromium with persistent profiles and manual authentication.
- Official `generic`, ChatGPT, Gemini, and DeepSeek adapters.
- DOM-based response streaming and canonical block output.
- File attachments, artifact hashing/storage, typed local hooks, Doctor, diagnostics, update workflow, and loopback bearer-authenticated API.
- Windows/Linux operational runbook and deterministic/unit/contract/integration/smoke test layers.
