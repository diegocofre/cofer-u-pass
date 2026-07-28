# Stage 2 — Extend model + effort contract to existing providers

Date: 2026-07-28
Target release: v1.3.0
Status: approved for implementation after Stage 1 manual validation

## Objective

Apply the provider-neutral model + reasoning-effort contract introduced and validated in Stage 1 to the existing Gemini and DeepSeek adapters, while preserving the Generic adapter as a capability-limited implementation when model/effort selection is not available.

This stage is primarily an adapter portability test. Core/API changes should be minimal and justified only by a provider-neutral deficiency revealed by a second or third implementation.

## Preconditions

Stage 1 is merged to `main` and manually validated against ChatGPT Web.

The following must already exist:

- public `model` + `reasoning.effort` semantics;
- provider-neutral inference domain types;
- inference configuration action and verification gate;
- catalog discovery/cache lifecycle;
- model-to-profile routing;
- worker catalog registration;
- deterministic contract tests for inference-capable adapters.

## Existing providers in scope

- Gemini
- DeepSeek
- Generic, only for explicit capability behavior and backward compatibility

## Architectural rule

Do not fork the Stage 1 core contract for provider-specific behavior.

Provider differences belong in adapter-owned discovery, normalization, selection, and verification logic. If a core change is required, it must be demonstrably provider-neutral and covered by contract tests.

## Gemini adapter

Implement the inference-selection adapter contract against the authenticated Gemini Web UI.

Requirements:

- discover the models actually selectable by the authenticated account;
- discover or derive the reasoning/thinking options actually exposed by the UI;
- map provider-native controls to normalized public effort values while preserving native labels/ids;
- select requested model and effort;
- verify effective model/effort before send;
- advertise only combinations/capabilities that can be selected and verified reliably;
- fail closed on unsupported/unverifiable selections.

Do not infer web capabilities solely from Gemini API documentation.

## DeepSeek adapter

Implement the same provider-neutral inference contract against authenticated DeepSeek Web.

Requirements mirror Gemini:

- discover actual web model choices;
- discover actual thinking/reasoning controls;
- normalize supported effort semantics without inventing unavailable levels;
- select and verify before send;
- advertise only proven web capabilities;
- preserve native labels/ids in diagnostics and run evidence.

If the UI exposes only a binary reasoning control, represent only the supported normalized semantics rather than fabricating a richer scale.

## Generic adapter

The Generic adapter must remain valid even when it cannot discover/select models or effort.

It must explicitly advertise absence of inference-selection capabilities and continue to support existing direct protocol workflows.

The shared engine/provider API must not require every adapter to implement inference selection.

## Catalog and routing

The model catalog may contain models from ChatGPT, Gemini, and DeepSeek simultaneously.

Requirements:

- deterministic public model ids;
- unambiguous routing to a ready authenticated profile;
- provider ownership metadata;
- provider/model-specific supported effort metadata;
- no profile credentials or browser internals exposed through public catalog/worker registration.

If identical model ids could collide across providers, introduce a provider-neutral public naming convention in the catalog layer rather than embedding browser profile ids.

## Contract tests

Create/reuse a shared adapter inference contract test suite.

For every adapter advertising model selection:

1. advertised catalog is non-empty;
2. each advertised model has a deterministic id;
3. requested known model can be selected in fixture DOM;
4. effective state can be read and verified;
5. unknown model is rejected before send.

For every adapter advertising effort selection:

1. advertised efforts are normalized and deterministic;
2. native labels remain available for evidence/diagnostics;
3. each advertised effort can be selected in fixture DOM;
4. effective effort is verified;
5. unsupported effort is rejected before send.

## Provider/API tests

Extend `/v1/models` and `/v1/responses` tests so one public request shape works across ChatGPT, Gemini, and DeepSeek by changing only `model` and optional `reasoning.effort`.

Verify mixed-provider catalog routing and ambiguity handling.

## Worker tests

Verify registration of models/efforts from multiple provider profiles and ensure the bridge payload remains provider-neutral.

## Supervised smoke tests

Document supervised smoke scenarios for Gemini and DeepSeek.

Each smoke test must capture evidence that requested model/effort was effective before submission. Exact response content alone does not prove correct inference selection.

## Documentation

Update:

- README provider matrix;
- provider exchange documentation;
- compatibility matrix;
- supervised smoke/runbook instructions;
- changelog for v1.3.0.

## Acceptance criteria

Stage 2 is complete when:

1. Gemini uses the Stage 1 contract without a provider-specific public API;
2. DeepSeek uses the Stage 1 contract without a provider-specific public API;
3. Generic remains backward-compatible without inference-selection capabilities;
4. one `/v1/responses` request schema works across all inference-capable existing providers;
5. `/v1/models` exposes a mixed provider catalog with correct effort metadata;
6. unsupported/unverifiable selections fail before send;
7. shared contract tests pass for all applicable adapters;
8. supervised Gemini and DeepSeek manual test procedures are documented;
9. no provider-specific core fork is introduced.

## Out of scope

- Kimi adapter;
- Z.AI/GLM adapter;
- tool/function-calling support;
- cross-provider automatic fallback;
- generalized provider plugin packaging beyond the current adapter registry.
