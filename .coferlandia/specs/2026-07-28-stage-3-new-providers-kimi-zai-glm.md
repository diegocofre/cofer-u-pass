# Stage 3 — New providers on the model + effort contract

Date: 2026-07-28
Target release: v1.4.0
Status: approved for implementation after Stage 2 manual validation

## Objective

Add new authenticated web providers only after the provider-neutral model + reasoning-effort contract has been proven by ChatGPT, Gemini, and DeepSeek.

New adapters must be born on the current contract. They must not introduce legacy profile-as-model behavior internally except where required for temporary public backward compatibility maintained by the shared provider service.

## Preconditions

Stages 1 and 2 are merged to `main` and manually validated.

The shared engine must already provide:

- inference model catalog;
- `model` + `reasoning.effort` request semantics;
- profile routing;
- inference configuration and verification gate;
- catalog cache/refresh lifecycle;
- worker model registration;
- reusable adapter inference contract tests.

## New providers in scope

1. Kimi
2. Z.AI web chat exposing GLM models

Use `zai` as the provider identity and GLM as the model family unless live reconnaissance proves a different stable product identity is required.

## Adapter creation requirements

Each new adapter must implement the existing provider lifecycle as applicable:

- navigation/home URL;
- authenticated/unauthenticated recognition;
- persistent browser profile compatibility;
- conversation open/continue/import where the site supports stable URLs;
- message input/send;
- response capture/generation-state detection;
- attachment upload if reliable;
- artifact download if reliable;
- model discovery;
- reasoning/effort discovery;
- inference selection;
- effective-state verification.

Capabilities must reflect observed, tested behavior rather than assumptions from vendor API documentation.

## Kimi adapter

Create an official `kimi` adapter package with manifest/rules and provider-specific logic.

Requirements:

- authenticate manually through managed Chromium and recognize successful authenticated state;
- discover the model selector exposed to the authenticated account;
- discover Kimi reasoning/intelligence modes exposed by the web UI;
- normalize native reasoning labels to the public effort contract while preserving native labels/ids;
- select requested model/effort and verify before send;
- implement conversation id extraction only if a stable URL identifier exists;
- implement attachments/artifacts only when they can be confirmed reliably;
- fail closed when requested inference state cannot be proven.

Do not hardcode a global Kimi model catalog.

## Z.AI / GLM adapter

Create an official `zai` adapter package with manifest/rules and provider-specific logic for the authenticated Z.AI web product.

Requirements:

- expose GLM family models through the shared public catalog;
- discover models actually available to the authenticated account;
- discover reasoning controls actually available in the web surface;
- normalize effort values through adapter-owned mapping while retaining native labels/ids;
- select and verify model/effort before send;
- support conversation, attachments, and artifacts only to the degree reliably observable in the web UI;
- fail closed on ambiguous or unverifiable inference state.

Do not call the provider `glm` merely because model names use the GLM family unless live product identity requires it.

## Public catalog behavior

New providers must appear automatically through the existing catalog/worker mechanisms once authenticated and discovered.

No special Kimi or Z.AI routing branches should be added to OpenAI-compatible endpoint handlers.

Public model ids must be deterministic and collision-safe under the convention stabilized in Stages 1–2.

## Shared adapter quality bar

A new provider is not considered supported merely because it can send a prompt.

It must pass:

- authentication-state tests;
- adapter manifest/rules consistency tests;
- inference contract tests;
- response canonicalization tests relevant to its DOM;
- pre-send verification tests;
- provider exchange routing tests;
- supervised live smoke documentation.

Capabilities unsupported by the provider must be omitted rather than emulated unreliably.

## Failure and safety semantics

Retain existing U Pass rules:

- never automate password, MFA, CAPTCHA, or verification-code entry;
- never replay an external message when outcome is uncertain;
- never silently substitute model or effort;
- never advertise a selectable capability that cannot be verified;
- preserve `outcome_unknown` semantics when an external effect may already have occurred.

## Tests

Add deterministic fixtures and tests for each provider covering at least:

- authenticated/unauthenticated recognition;
- model discovery;
- effort discovery/normalization;
- selection and verification;
- unsupported model/effort rejection;
- message submission evidence;
- response capture;
- registry integration;
- model catalog ownership/routing;
- worker registration.

Add supervised smoke entry points for `kimi` and `zai` to the existing provider smoke infrastructure.

## Documentation

Update:

- README official adapter list/provider matrix;
- compatibility matrix;
- provider exchange documentation;
- authentication/runbook examples;
- supervised smoke instructions;
- changelog for v1.4.0.

## Acceptance criteria

Stage 3 is complete when:

1. Kimi is an official adapter using the shared model + effort contract;
2. Z.AI/GLM is an official adapter using the same contract;
3. neither provider requires provider-specific public request fields;
4. both providers participate in `/v1/models` and worker registration through shared mechanisms;
5. requested inference state is verified before message submission;
6. unsupported or unverifiable capabilities fail closed;
7. deterministic tests pass;
8. supervised manual smoke procedures are documented;
9. adding these providers required adapter/catalog work rather than another redesign of the engine contract.

## Out of scope

- automatic failover between web subscriptions;
- vendor API-key integrations;
- tool/function-calling emulation through provider web UIs;
- browser credential export to Cofer One IA;
- generalized third-party adapter marketplace/plugin loading.
