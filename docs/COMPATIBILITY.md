# Compatibility matrix — v1.2.0

| Component | Supported baseline |
| --- | --- |
| Python | 3.11, 3.12, 3.13 |
| OS | Windows 10/11; mainstream x86_64 Linux distributions |
| Browser | Playwright-managed Chromium installed by the matching Playwright package |
| Protocol contract | 1.x |
| Event contract | 1.0 |
| Canonical block contract | 1.0 |
| Adapter rule schema | 1.0 |
| SQLite schema | 1 |
| Restricted provider exchange | `cofer-u-pass.exchange/1` |

Provider adapters are versioned independently inside the package. Live provider compatibility must be validated by supervised smoke tests before a stable release because provider DOM/UI changes are outside repository control.

## Inference selection support

| Adapter | Direct profile protocols | Restricted text/file provider | Model discovery | Model selection | `reasoning.effort` selection | Verification before send |
| --- | --- | --- | --- | --- | --- | --- |
| `chatgpt` | Yes | Yes | Yes, v1.2 | Yes, v1.2 | Yes, v1.2 | Yes, v1.2 |
| `gemini` | Yes | Legacy/profile route | Not yet | Not yet | Not yet | Not yet |
| `deepseek` | Yes | Legacy/profile route | Not yet | Not yet | Not yet | Not yet |
| `generic` | Yes | Capability-dependent | No | No | No | No |

Stage 1 intentionally implements the new inference contract only for ChatGPT. Gemini and DeepSeek are scheduled to adopt the same provider-neutral contract in Stage 2 rather than receiving provider-specific public fields.

## v1.1 compatibility

A ready authenticated profile id remains accepted temporarily as the restricted provider `model` when `reasoning.effort` is omitted. This keeps v1.1 clients working while the real model catalog is introduced.

Legacy profile ids are not returned by `/v1/models` once real discovered models are available. New integrations should use the discovered model id and optional `reasoning.effort`.

## Public effort vocabulary

v1.2 accepts the normalized OpenAI-compatible values:

`none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`.

A provider model advertises only the subset discovered and verifiable for the authenticated account. Provider-native labels remain adapter metadata and are not assumed to be semantically identical across vendors.
