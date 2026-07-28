# Validation Report — v1.1.0

Validation date: 2026-07-28

## Completed in this build environment

- Deterministic/unit/contract/API test suite: 57 passed, 2 skipped in the final deterministic suite.
- Exchange protocol validation, safe paths, and output contracts.
- ZIP traversal, symlink/special-entry, nested-archive, expanded-size, entry-count, depth, and required-output-member protections.
- Restricted provider request compilation and explicit tool/function-calling rejection.
- Provider Files API upload/content/delete behavior.
- Worker file-reference discovery and artifact publication behavior.
- Existing run/state/checkpoint/recovery, CLI chat, API/SSE, adapter-contract, and migration coverage remains green.

## Environment-limited validation

The controlled Chromium integration test is included but skipped because Playwright Chromium is not installed in this build container. Live provider smoke tests remain supervised and require manually authenticated profiles.

The real ChatGPT profile flow established in v1.0.x remains the basis for the v1.1 artifact smoke gate: authenticated profile detection, new conversation, message submission, DOM capture, continuation, and canonical results have already been exercised on Windows. Provider-generated ZIP/download behavior must be smoke-tested on the user's authenticated ChatGPT profile after installation because it depends on live web-product UI.

## v1.1 live acceptance gate

1. Start Cofer One IA with `COFER_U_PASS_MODELS=cupass-chatgpt=chatgpt-main`.
2. Start `cofer-u-pass worker --profile chatgpt-main` with the matching bridge key.
3. Verify the gateway lists `cupass-chatgpt` and its capabilities report `tools=false`.
4. Send a plain `/v1/responses` request and verify a text response.
5. Upload a context ZIP through `/v1/files`, request a named output ZIP with at least one required member, download the returned bridge file, and verify hashes/members.
6. Send a request containing `tools` and verify a deterministic client error without browser execution.

## Required release-gate commands

See `RUNBOOK.md` and `scripts/release_check.py` for package-level release checks.

## Final wheel

- `cofer_u_pass-1.1.0-py3-none-any.whl`
- SHA-256: `a630a504760a67f5c7495de0085255c906a64f09e9c9d9efd0c7e5fc9c698e45`
- sdist SHA-256: `40e6763e1c449145528c1c43305336e678a4ed85e7ed95c5d95e13334025b3e3`
- Bundled exchange/config schemas, exchange example, provider service, and worker verified present in release artifacts.
