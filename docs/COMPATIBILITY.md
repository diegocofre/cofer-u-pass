# Compatibility matrix — v1.0.0

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

Provider adapters are versioned independently inside the package. Live ChatGPT, Gemini, and DeepSeek compatibility must be validated by supervised smoke tests before a stable release because provider DOM/UI changes are outside repository control.
