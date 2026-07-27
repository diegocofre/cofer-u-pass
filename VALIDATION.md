# Validation Report — v1.0.6

Validation date: 2026-07-27

## Completed in this build environment

- Deterministic/unit/contract/integration tests: 37 passed, 2 skipped.
- CLI regression coverage now includes the interactive `chat` façade, conversation-id reuse, `/new`, and command registration/help.
- Adapter contract tests that do not require live provider accounts.
- API/SSE integration tests.
- SQLite migration and recovery tests.
- Path, profile, sanitization, and external-effect safety tests.
- Wheel build and inspection.
- Wheel installation into an isolated target directory using the build environment's already-installed runtime dependencies.
- Installed-wheel validation for `--version`, adapter imports, bundled `ask.yaml`, and `chat --help`.

## Environment-limited validation

A fully dependency-resolving fresh virtual-environment install was not required for this patch. The wheel was installed into an isolated target while reusing the build environment's runtime dependencies.

The controlled Chromium integration test is included but could not be executed in this build environment because Playwright Chromium is not installed here.

The live ChatGPT, Gemini, and DeepSeek smoke tests are intentionally supervised and require manually authenticated persistent profiles. They were not run in this build environment because no authenticated provider profiles were supplied.

## Live findings already incorporated

- v1.0.1: ChatGPT anonymous composer could cause an authentication false positive.
- v1.0.2: visible/headless authentication verification differs for real ChatGPT profiles on Windows; Windows mandatory profile locks also required explicit contention handling.
- v1.0.3: authenticated provider UI can mount after `DOMContentLoaded`, requiring bounded polling.
- v1.0.4: run preflight needed the same authentication wait, and CLI shutdown needed an executor-cleanup barrier.
- v1.0.5: the first successful real ChatGPT end-to-end run exposed duplicate derived plain text when container fallback text duplicated child text.
- v1.0.6: adds an interactive CLI chat façade after real continuation was validated against the same ChatGPT conversation. Every chat turn remains an ordinary immutable run and reuses only the persisted `conversation_id`.

## Current chat UX boundary

`cofer-u-pass chat` intentionally does not create a second long-lived execution engine. Each message remains a separate run, so visible-only adapters may open Chromium for every turn. The terminal prints the canonical response when the turn completes; persisted `response.delta` events remain available to the engine but are not yet rendered as a character-perfect terminal stream.

## Required release-gate commands

See `RUNBOOK.md` and `scripts/release_check.py` for the operational release procedure.
