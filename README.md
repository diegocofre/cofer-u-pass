# Cofer U Pass

Cofer U Pass is a local, agent-independent automation layer for authenticated AI web applications. It executes trusted, versioned protocols through a Playwright-managed Chromium profile and exposes one shared engine through an async Python API, CLI, and loopback HTTP/SSE API.

Official v1 adapters: `generic`, `chatgpt`, `gemini`, and `deepseek`.

## Install

```bash
uv tool install cofer-u-pass==1.0.0
cofer-u-pass setup
cofer-u-pass doctor
```

or:

```bash
pipx install cofer-u-pass==1.0.0
cofer-u-pass setup
```

Create and authenticate a profile:

```bash
cofer-u-pass profiles create my-chatgpt --provider chatgpt
cofer-u-pass profiles authenticate my-chatgpt
```

Run the example protocol:

```bash
cofer-u-pass run examples/ask.yaml --profile my-chatgpt --input prompt="Explain event sourcing in five sentences."
```

For an interactive terminal conversation backed by the same persisted run engine:

```bash
cofer-u-pass chat --profile my-chatgpt
```

Inside chat, use `/id` to show the persisted conversation id, `/new` to start a fresh conversation, `/help` for commands, and `/exit` to leave. Each message is still an ordinary immutable Cofer U Pass run.

Start the local API:

```bash
cofer-u-pass serve
```

See [`docs/RUNBOOK.md`](docs/RUNBOOK.md) for complete operation, recovery, security, and platform procedures.

## Safety model

Cofer U Pass never automates passwords, MFA, CAPTCHA, or verification codes. External-effect actions are journaled and are not automatically repeated when the engine cannot prove whether the effect already happened. In that case the run becomes `outcome_unknown`.

## License

Apache-2.0. Copyright © 2026 Diego Cofré / dc sistemas.
