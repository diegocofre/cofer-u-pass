# Adapters

Each provider package contains trusted Python behavior, a versioned `manifest.json`, and versioned declarative `rules.json`. Rules describe accessible/DOM locators, capabilities, authentication signals, response containers, generation state, attachments, and artifacts. Rules cannot execute code.

Locator preference is accessible role/label first and CSS as a fallback. `resolve()` requires visible, unique matches unless an operation explicitly needs a collection. Ambiguity raises `adapter_mismatch` rather than guessing.

Provider UIs are external moving targets. Stable releases require supervised smoke tests with manually authenticated profiles; those tests are intentionally excluded from CI.
