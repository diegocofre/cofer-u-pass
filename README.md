# Cofer U Pass

Cofer U Pass is a local, agent-independent automation layer for authenticated AI web applications. It executes trusted, versioned protocols through a Playwright-managed Chromium profile and exposes one shared engine through an async Python API, CLI, loopback HTTP/SSE API, and a restricted OpenAI-compatible text/file exchange surface.

Official adapters: `generic`, `chatgpt`, `gemini`, and `deepseek`.

## Install

```bash
uv tool install cofer-u-pass==1.1.0
cofer-u-pass setup
cofer-u-pass doctor
```

or:

```bash
pipx install cofer-u-pass==1.1.0
cofer-u-pass setup
```

Create and authenticate a profile:

```bash
cofer-u-pass profiles create my-chatgpt --provider chatgpt
cofer-u-pass profiles authenticate my-chatgpt
```

Run a protocol directly:

```bash
cofer-u-pass run examples/ask.yaml --profile my-chatgpt --input prompt="Explain event sourcing in five sentences."
```

Or use the interactive terminal façade:

```bash
cofer-u-pass chat --profile my-chatgpt
```

## Restricted provider mode

v1.1 lets Cofer U Pass profiles appear behind an OpenAI-compatible inference gateway while keeping the web model deliberately restricted:

- text input/output: supported;
- uploaded files and images by `file_id`: supported when the adapter can attach them;
- downloadable files and ZIP bundles: supported when the adapter can download provider artifacts;
- `tools`, function calling, and autonomous tool loops: explicitly unsupported.

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

The local API exposes `/v1/models`, `/v1/models/{profile}/capabilities`, `/v1/files`, and `/v1/responses`. Use a compact JSON string in `metadata.cofer_protocol`, or upload a protocol file and reference its `file-*` ID in `metadata.cofer_protocol_file`. Uploaded files are referenced with Responses-style `input_file` parts. Provider-generated ZIPs are treated as untrusted data and validated before they are published as artifacts.

## Cofer One IA worker

Cofer One IA can list a profile such as `chatgpt-main` as a logical model such as `cupass-chatgpt`. Its Docker bridge stays separate from the browser runtime; Cofer U Pass connects outward from the host:

```bash
export COFER_U_PASS_BRIDGE_KEY='<same key configured by Cofer One IA>'
cofer-u-pass worker --bridge http://127.0.0.1:4011 --profile chatgpt-main
```

The worker downloads request files, executes an ordinary immutable Cofer U Pass run, uploads resulting artifacts to the bridge, and keeps a heartbeat during long web tasks. The bridge never receives browser cookies or profile data.

See [`docs/PROVIDER-EXCHANGE.md`](docs/PROVIDER-EXCHANGE.md) for provider-mode operation and [`RUNBOOK.md`](RUNBOOK.md) for the existing local runtime/recovery procedures.

## Safety model

Cofer U Pass never automates passwords, MFA, CAPTCHA, or verification codes. External-effect actions are journaled and are not automatically repeated when the engine cannot prove whether the effect already happened. In that case the run becomes `outcome_unknown`.

## License

Apache-2.0. Copyright © 2026 Diego Cofré / dc sistemas.
