# Stage 1 — ChatGPT model + effort contract

Date: 2026-07-28
Target release: v1.2.0
Status: approved for implementation

## Objective

Evolve Cofer U Pass so its restricted OpenAI-compatible provider surface exposes real provider models through `model` and maps the OpenAI reasoning effort control to the intelligence/reasoning control available in ChatGPT Web.

ChatGPT is the first implementation and the proving ground for the general contract. This stage is not a ChatGPT-only shortcut: the core contract must be reusable by future adapters without provider-specific fields leaking into the public API.

## Current state

In v1.1, `/v1/models` exposes authenticated browser profiles as logical models, and `/v1/responses.model` is interpreted as a `profile_id`. Profiles represent authentication/browser identity, not inference identity.

The ChatGPT adapter already supports authenticated conversations, message submission, response capture, file attachment, and artifact download.

## Target contract

A provider request selects inference independently from authentication:

```json
{
  "model": "<provider-model-id>",
  "reasoning": {
    "effort": "<normalized-effort>"
  },
  "input": "..."
}
```

Definitions:

- `profile`: authenticated provider/browser identity; internal routing concern.
- `model`: provider model exposed through the public model catalog.
- `reasoning.effort`: normalized reasoning/intelligence selection requested by the client.
- provider-native labels/identifiers remain internal adapter metadata.

The public contract must not require ChatGPT-specific field names or visible UI labels.

## Domain model

Introduce provider-neutral inference types sufficient to represent:

- advertised model id;
- provider id;
- display label;
- supported normalized effort values;
- optional native model identifier/label;
- optional native effort identifier/label;
- resolved authenticated profile;
- requested and effective inference state.

A suggested conceptual split is:

- `ProviderModel`
- `InferenceSelection`
- `InferenceState`
- `ResolvedInferenceTarget`

Exact class names may change if repository conventions suggest a better fit.

## Adapter contract

Extend `ProviderAdapter` with optional inference-selection capabilities.

The adapter contract must support:

1. discovering the models currently available to the authenticated account;
2. discovering/advertising supported effort values when possible;
3. reading the current effective model/effort state;
4. applying a requested model/effort;
5. verifying effective state before message submission.

Capabilities should distinguish at least:

- model discovery;
- model selection;
- effort selection;
- inference-state verification.

Adapters that do not implement these capabilities must continue to work for existing direct protocol execution.

## ChatGPT implementation

The ChatGPT adapter must inspect the authenticated ChatGPT Web UI and derive the selectable model/intelligence controls actually available to that account.

Requirements:

- do not maintain a global hardcoded list of current ChatGPT models;
- prefer stable DOM identifiers/attributes over translated visible text when available;
- preserve native labels/ids for diagnostics;
- normalize provider-native intelligence labels to public effort values through adapter-owned mapping;
- never silently downgrade or substitute model/effort;
- if the requested selection cannot be verified, fail before the prompt is submitted.

A small adapter-owned compatibility map for stable semantic normalization is acceptable; a product-wide hardcoded model catalog is not.

## Execution plan

Add a first-class inference configuration step between conversation opening and any external message submission:

```text
open_conversation
configure_inference
attach_files (optional)
send_message
capture_response
download_artifacts (optional)
finalize
```

`configure_inference` must record evidence containing requested and effective model/effort and whether verification succeeded.

The executor must not run `send_message` unless the requested inference state was verified when the protocol/request requires inference configuration.

## Restricted provider service

Change the provider exchange semantics so:

- `/v1/models` advertises real provider models rather than browser profile ids;
- `reasoning.effort` is parsed and validated;
- a model request resolves internally to an authenticated profile/provider;
- the generated internal protocol carries inference selection explicitly;
- the final canonical result metadata records requested/effective inference information.

The provider service must retain rejection of unsupported tool/function-calling semantics.

## Profile routing

The first implementation may assume one ready authenticated profile for a given provider/model if that is the only unambiguous configuration.

Routing must fail clearly when no ready profile can serve the requested model or when multiple candidates make routing ambiguous without an explicit configured preference.

Do not encode `profile_id` into the public model id solely to avoid solving routing.

## Catalog lifecycle

Model discovery is browser/UI work and must not execute on every `/v1/models` request.

Implement a derived catalog cache per authenticated profile. The cache must be safely rebuildable from the provider UI and may live outside SQLite if it is fully reconstructable.

Required behaviors:

- refresh after authentication or explicit request;
- expose cached models through `/v1/models`;
- on selection failure plausibly caused by stale catalog, allow at most one bounded refresh/retry before failing closed;
- never loop indefinitely or send using an unverified fallback.

Expose CLI inspection/refresh commands for a profile's model catalog.

## Backward compatibility

Preserve existing direct CLI/protocol workflows using `--profile`.

For the restricted provider API, support the v1.1 profile-id-as-model form as a temporary legacy alias where practical. The alias may use the provider's currently selected/default inference state, but it must not be newly advertised as the preferred model catalog entry.

Document the compatibility behavior explicitly.

## Worker / Cofer One IA exchange

The outbound worker registration must evolve from profile-only registration to include the models and supported effort values exposed by each ready profile.

Browser profiles/cookies remain local to the host. Cofer One IA receives only routing/catalog metadata needed to expose models.

The existing restricted text/file semantics remain unchanged.

## Persistence and migrations

Prefer derived catalog storage and run/action metadata over a SQLite schema migration unless durable relational state is genuinely required.

Any required schema migration must include an explicit compatible migration path; never increment the schema version without migration support.

## Failure semantics

The following must fail before `send_message`:

- unknown model;
- unsupported effort;
- requested model unavailable to authenticated account;
- requested effort unavailable for the selected model;
- ambiguous routing;
- inability to confirm effective model/effort;
- provider UI mismatch while configuring inference.

If failure occurs after a message may have been submitted, existing `outcome_unknown` semantics continue to apply.

## Tests

Deterministic tests must cover:

- parsing `reasoning.effort`;
- model catalog serialization;
- model-to-profile routing;
- legacy profile alias behavior;
- model discovery fixtures;
- effort discovery/normalization fixtures;
- model selection;
- effort selection;
- effective-state verification;
- unsupported model/effort rejection before send;
- stale catalog bounded refresh;
- optional inference capabilities for adapters that do not support selection;
- worker registration of model metadata;
- API `/v1/models` and `/v1/responses` contract.

Add a supervised ChatGPT smoke path that proves two different effort selections using the same model where the authenticated account exposes them. Evidence must verify the selected model/effort before submission; response text alone is not sufficient proof.

## Documentation

Update at least:

- README restricted provider examples;
- provider exchange documentation;
- compatibility documentation;
- runbook/model catalog refresh instructions;
- changelog for v1.2.0.

## Acceptance criteria

Stage 1 is complete when:

1. an OpenAI-compatible client can request a real ChatGPT model through `model`;
2. the same request can set `reasoning.effort`;
3. U Pass resolves the request to the authenticated ChatGPT profile internally;
4. ChatGPT Web model and intelligence controls are selected and verified before send;
5. `/v1/models` returns the discovered ChatGPT model catalog with effort metadata;
6. unsupported/unverifiable selections fail closed before external message submission;
7. existing direct `--profile` workflows remain functional;
8. deterministic tests pass;
9. a supervised real ChatGPT smoke test procedure is documented;
10. worker registration exposes the new model/effort catalog without exposing browser credentials.

## Out of scope

- Gemini/DeepSeek implementation of the new contract;
- Kimi or Z.AI/GLM adapters;
- tool/function-calling support;
- autonomous model fallback;
- semantic claims that provider-native effort levels are computationally identical across vendors.
