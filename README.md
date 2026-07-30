# Cofer U Pass

Cofer U Pass is a local, agent-independent automation layer for authenticated AI web applications. It executes trusted, versioned protocols through a Playwright-managed Chromium profile and exposes one shared engine through an async Python API, CLI, loopback HTTP/SSE API, and a restricted OpenAI-compatible text/file exchange surface.

Official adapters: `generic`, `chatgpt`, `gemini`, and `deepseek`. In v1.2, ChatGPT is the first adapter that exposes provider model discovery plus verified model/reasoning selection through the public inference contract.

## Install

```bash
uv tool install cofer-u-pass==1.2.7
cofer-u-pass setup
cofer-u-pass doctor
```

or:

```bash
pipx install cofer-u-pass==1.2.7
cofer-u-pass setup
```

Create and authenticate a profile:

```bash
cofer-u-pass profiles create my-chatgpt --provider chatgpt
cofer-u-pass profiles authenticate my-chatgpt
cofer-u-pass profiles models my-chatgpt
```

Authentication is still a browser/profile concern. The derived model catalog is separate and may be refreshed explicitly:

```bash
cofer-u-pass profiles models my-chatgpt --refresh
```

Run a protocol directly by profile as before:

```bash
cofer-u-pass run examples/ask.yaml --profile my-chatgpt --input prompt="Explain event sourcing in five sentences."
```

Or use the interactive terminal façade:

```bash
cofer-u-pass chat --profile my-chatgpt
```

## Restricted provider mode

The restricted OpenAI-compatible surface separates authentication from inference identity:

- `profile`: internal authenticated browser/account route;
- `model`: discovered provider model;
- `reasoning.effort`: normalized reasoning/intelligence request;
- text input/output: supported;
- uploaded files and images by `file_id`: supported when the adapter can attach them;
- downloadable files and ZIP bundles: supported when the adapter can download provider artifacts;
- `tools`, function calling, and autonomous tool loops: explicitly unsupported.

After refreshing a ChatGPT profile catalog, `GET /v1/models` advertises the discovered model ids and their supported effort values. A request can then use the normal Responses-style shape:

```json
{
  "model": "gpt-5.6-sol",
  "reasoning": {"effort": "high"},
  "input": "Explain event sourcing in five sentences."
}
```

The ChatGPT adapter selects the requested web model and intelligence control and verifies the effective state before `send_message`. Unknown, ambiguous, unsupported, or unverifiable selections fail closed; Cofer U Pass does not silently downgrade inference.

The v1.1 profile-id-as-model form remains accepted temporarily when no `reasoning.effort` is supplied, but profile ids are no longer advertised by `/v1/models` as preferred model entries.

The task itself always stays in the prompt. An optional `cofer-u-pass.exchange/1` protocol only controls transport and output validation. For example:

```json
{
  "schema": "cofer-u-pass.exchange/1",
  "output": {
    "kind": "bundle",
    "filename": "architecture.zip",
    "required_files": ["SPEC.md"]
  }
}
```

The local API exposes `/v1/models`, `/v1/models/{model}/capabilities`, `/v1/files`, and `/v1/responses`. Use a compact JSON string in `metadata.cofer_protocol`, or upload a protocol file and reference its `file-*` ID in `metadata.cofer_protocol_file`. Uploaded files are referenced with Responses-style `input_file` parts. Provider-generated ZIPs are treated as untrusted data and validated before they are published as artifacts.

## Cofer One IA worker

The host worker still registers authenticated profiles for leasing compatibility, but v1.2 also includes each profile's derived model catalog and supported effort metadata in registration. The Docker bridge remains separate from Chromium and never receives browser cookies/profile contents:

```bash
export COFER_U_PASS_BRIDGE_KEY='<same key configured by Cofer One IA>'
cofer-u-pass worker --bridge http://127.0.0.1:4011 --profile my-chatgpt
```

The worker downloads request files, resolves a requested public model to the local authenticated profile, executes an ordinary immutable Cofer U Pass run, uploads resulting artifacts, and keeps a heartbeat during long web tasks.

See [`docs/PROVIDER-EXCHANGE.md`](docs/PROVIDER-EXCHANGE.md) for provider-mode semantics, [`docs/MODEL-CATALOG-RUNBOOK.md`](docs/MODEL-CATALOG-RUNBOOK.md) for catalog operations and Stage 1 supervised validation, and [`RUNBOOK.md`](RUNBOOK.md) for the general local runtime/recovery procedures.

## Safety model

Cofer U Pass never automates passwords, MFA, CAPTCHA, or verification codes. External-effect actions are journaled and are not automatically repeated when the engine cannot prove whether the effect already happened. In that case the run becomes `outcome_unknown`.

Inference configuration is a pre-send safety gate: if the requested model or reasoning effort cannot be proven effective in the provider UI, the prompt is not submitted.

## License

Apache-2.0. Copyright © 2026 Diego Cofré / dc sistemas.
