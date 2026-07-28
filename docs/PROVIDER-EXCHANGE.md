# Restricted Provider Exchange — v1.2

Cofer U Pass can expose authenticated AI web subscriptions through a restricted OpenAI-compatible text/file surface. Authentication remains tied to a local browser `profile`; inference identity is exposed independently as a discovered provider `model` plus optional `reasoning.effort`.

This is intentionally **not** tool emulation: `tools`, function calling, and non-`none` `tool_choice` are rejected.

## Capabilities

The provider supports text input/output, Files-API uploads, input bundles, downloadable provider files, and validated ZIP bundles. Streaming is currently buffered. Tool/function-calling semantics are unsupported by contract.

Stage 1 / v1.2 adds provider-neutral inference selection and implements it for ChatGPT Web:

- discovered provider models are advertised by `/v1/models`;
- supported normalized effort values are exposed as model metadata;
- `POST /v1/responses` accepts `reasoning.effort`;
- U Pass resolves the requested model to an authenticated local profile;
- model and effort are selected in the provider UI and verified before `send_message`;
- no silent model/effort fallback is allowed.

Gemini and DeepSeek retain their v1.1 restricted-provider behavior until the same inference contract is implemented for them in Stage 2.

## Local API

Start the local service with `cofer-u-pass serve`. Its OpenAI-compatible exchange surface is:

- `GET /v1/models`
- `GET /v1/models/{model}/capabilities`
- `POST /v1/files`
- `GET /v1/files/{file_id}`
- `GET /v1/files/{file_id}/content`
- `DELETE /v1/files/{file_id}`
- `POST /v1/responses`

All endpoints retain the normal Cofer U Pass loopback bearer-token policy.

## Model catalog

Provider model discovery requires an authenticated browser session and is intentionally not performed on every `/v1/models` call.

Inspect the cached catalog:

```bash
cofer-u-pass profiles models chatgpt-main
```

Rediscover it from ChatGPT Web:

```bash
cofer-u-pass profiles models chatgpt-main --refresh
```

A successful CLI authentication also attempts a best-effort refresh. Authentication remains successful if the provider UI has changed and discovery fails; the derived catalog records the discovery error and can be retried explicitly.

The catalog is rebuildable derived data under the U Pass data root, not authoritative browser/profile state. A failed refresh does not continue serving stale models as current models.

## Responses request

For a discovered ChatGPT model:

```json
{
  "model": "gpt-5.6-sol",
  "reasoning": {
    "effort": "high"
  },
  "input": "Explain event sourcing in five sentences."
}
```

The public effort vocabulary accepted by v1.2 is:

```text
none, minimal, low, medium, high, xhigh, max
```

A model advertises only the effort values the adapter discovered for that authenticated account. Passing a public effort value that the selected model does not advertise fails before a run sends a message.

The actual visible/provider-native model and effort labels are adapter details retained in run evidence and diagnostics; callers do not need to know them.

## Failure behavior

Before message submission U Pass fails closed on:

- unknown model;
- ambiguous model routing across multiple ready profiles;
- unsupported effort;
- stale catalog that remains invalid after one bounded refresh;
- provider picker mismatch;
- inability to verify the effective model;
- inability to verify the requested reasoning effort.

There is no automatic model downgrade or cross-provider fallback.

If a failure occurs after an external message may already have been submitted, the existing `outcome_unknown` rules remain authoritative.

## v1.1 compatibility

A ready authenticated profile id such as `chatgpt-main` is still accepted temporarily as `model` when no `reasoning.effort` is supplied. This legacy form uses the provider's current/default inference state and exists only to avoid breaking v1.1 clients.

Legacy profile ids are not advertised by `/v1/models`. New clients should discover a real model id and send that id in `model`.

## Files and output protocol

A plain text response requires no exchange protocol. For file/bundle output, use the minimal `cofer-u-pass.exchange/1` contract. The task/role remains entirely in the prompt.

```json
{
  "schema": "cofer-u-pass.exchange/1",
  "input": {"strategy": "auto"},
  "output": {
    "kind": "bundle",
    "filename": "architecture.zip",
    "required_files": ["SPEC.md"],
    "optional_files": ["DECISIONS.md"],
    "allow_extra_files": true
  }
}
```

For a small protocol, pass compact JSON as a **string** in `metadata.cofer_protocol`. For larger protocols, upload the JSON through `/v1/files` and pass its ID in `metadata.cofer_protocol_file`.

Input ZIPs are treated as untrusted data. Cofer U Pass rejects path traversal, absolute paths, symlink/special entries, nested archives, excessive depth/entry count, per-file limits, and excessive expanded size. Provider-generated ZIP bundles are validated again before success is returned.

## Cofer One IA worker

Cofer One IA keeps a Docker bridge separate from Chromium. The host worker initiates the connection outward, so the normal Cofer U Pass API remains loopback-only and browser profiles/cookies never enter Docker.

Git Bash:

```bash
export COFER_U_PASS_BRIDGE_KEY='<same value as cofer-one-ia/.env>'
cofer-u-pass worker \
  --bridge http://127.0.0.1:4011 \
  --profile chatgpt-main
```

Worker registration retains the original profile metadata used for leasing and adds the derived model entries, supported reasoning efforts, catalog timestamp, and catalog error. This is additive on the U Pass side; the bridge remains responsible for deciding how that metadata is surfaced to clients.

The worker long-polls for jobs, keeps a heartbeat during long browser execution, streams request/output files in bounded chunks, and uploads provider artifacts back to the bridge.

If the worker disappears while a job is leased, that job must not be replayed blindly: an external message may already have been submitted. The bridge is expected to fail closed and surface an uncertain external outcome instead of automatically duplicating the work.

See [`MODEL-CATALOG-RUNBOOK.md`](MODEL-CATALOG-RUNBOOK.md) for catalog recovery and the supervised Stage 1 ChatGPT validation procedure.
