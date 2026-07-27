# Cofer U Pass

## Product and Technical Specification — v1

Status: Approved conceptual design consolidated for implementation  
Specification version: 1.0  
Target product version: 1.x  
Last updated: 2026-07-26

---

## 1. Purpose

Cofer U Pass is a local, agent-independent automation layer for authenticated AI web applications. It allows a trusted local program to execute versioned protocols against supported providers through a Playwright-managed Chromium session while preserving streaming, artifacts, structured output, execution evidence, and safe recovery semantics.

The v1 product exposes the same capabilities through:

- An asynchronous Python library.
- A command-line interface.
- A local HTTP API with Server-Sent Events.

All three interfaces are façades over the same application service. They MUST share the same domain contracts and MUST NOT contain provider-specific browser automation logic.

The initial official providers are:

- ChatGPT.
- Gemini.
- DeepSeek.
- A constrained `generic` adapter for contract testing and explicitly supported generic flows.

Cofer U Pass is not a general-purpose autonomous browser agent. It executes approved, declarative protocols through trusted, versioned adapters.

---

## 2. Product principles

The implementation MUST preserve the following principles:

1. **Agent independence**  
   No calling agent, IDE, CLI, orchestrator, or model provider owns the execution semantics.

2. **One engine, equivalent interfaces**  
   Python, CLI, and HTTP/SSE MUST execute the same use cases and produce equivalent events and results.

3. **Declarative intent, imperative adapters**  
   Protocols describe intent and sequence. Provider-specific behavior, UI knowledge, and selectors belong to adapters.

4. **Manual authentication**  
   The user authenticates in a visible browser. Cofer U Pass never requests, fills, intercepts, or stores passwords, MFA secrets, CAPTCHA answers, or verification codes.

5. **Safety before retry**  
   An external effect MUST NOT be repeated unless the engine can demonstrate that it did not already occur.

6. **DOM as the canonical response source**  
   Provider output is captured from the rendered DOM. Network observation is optional and diagnostic only.

7. **Local-first privacy**  
   There is no telemetry or automatic diagnostic upload. Browser profiles, execution state, and evidence remain local.

8. **Explicit compatibility**  
   Engine, protocol, adapter, schema, hook, Chromium, and database versions are validated before execution.

9. **Reproducible diagnosis**  
   UI regressions and runtime failures produce minimal, sanitized evidence suitable for isolated repair.

10. **No silent operational changes**  
    Installation, updates, migrations, rollback, cleanup, and adapter activation are explicit and auditable.

---

## 3. Normative language

The terms **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are normative.

- **MUST / MUST NOT** define acceptance requirements.
- **SHOULD / SHOULD NOT** define defaults that may be changed only with a documented reason.
- **MAY** defines optional behavior.

---

## 4. v1 scope

### 4.1 Included

The v1 release MUST include:

- An asynchronous Python library, CLI, and local HTTP/SSE API.
- A declarative, versioned protocol engine.
- Immutable execution planning.
- Official `generic`, ChatGPT, Gemini, and DeepSeek adapters.
- Playwright-managed Chromium.
- Persistent browser profiles with manual authentication.
- New conversations, explicit continuation, and explicit conversation import.
- Message submission and file attachments.
- Faithful response streaming.
- Canonical block trees with derived Markdown and plain text.
- Artifact downloads with integrity metadata.
- A per-profile execution queue and exclusive profile access.
- Parallel execution across different profiles, subject to a global limit.
- Persistent events, journals, checkpoints, cancellation, reconciliation, and safe resume.
- Explicit `authentication_required`, `recoverable`, and `outcome_unknown` states.
- Typed Python hooks executed in separate processes.
- SQLite persistence, migrations, backups, and filesystem artifact storage.
- Preventive and reactive Doctor workflows.
- Sanitized diagnostic packages.
- Installation from PyPI with `uv tool` and `pipx`.
- Official Windows and Linux support.
- Complete technical documentation and a verified operational `RUNBOOK.md`.

### 4.2 Explicitly excluded

The following are outside v1:

- Remote, multi-user, or multi-tenant service operation.
- API exposure beyond loopback.
- Docker images or standalone native installers.
- Password, MFA, or CAPTCHA automation.
- CDP attachment to arbitrary external browsers.
- Dynamic adapter, protocol, or code marketplaces.
- Remote code download or execution.
- JavaScript or arbitrary code embedded in protocols or declarative rules.
- Automatic adapter repair, publication, or activation.
- Unconstrained generic web automation.
- Telemetry or automatic diagnostic uploads.
- Official macOS support.
- Mobile browser support.
- Guaranteed performance SLAs.

---

## 5. System architecture

### 5.1 Logical modules

The system is divided into seven major areas:

1. **Public interfaces**  
   Python library, CLI, and HTTP/SSE.

2. **Application and protocol engine**  
   Validation, planning, execution, queueing, cancellation, reconciliation, and resume.

3. **Domain contracts**  
   Runs, actions, states, events, protocols, blocks, artifacts, checkpoints, and compatibility contracts.

4. **Browser runtime**  
   Playwright, managed Chromium, persistent profiles, navigation controls, and process lifecycle.

5. **Adapters**  
   Provider behavior, manifests, capabilities, declarative rules, fixtures, and contract implementations.

6. **Persistence**  
   SQLite, migrations, filesystem storage, hashes, retention, and backups.

7. **Doctor**  
   Preventive checks, failure classification, evidence capture, sanitization, and reproducible diagnostic packages.

### 5.2 Dependency direction

The dependency direction MUST remain strict:

- CLI, API, and library depend on application use cases.
- Application use cases depend on domain contracts and inward-facing ports.
- Browser, persistence, adapters, hooks, and filesystem components implement those ports.
- The domain MUST NOT depend on HTTP, CLI, Playwright, SQLite, filesystem details, or providers.
- Adapters MUST NOT introduce provider-specific branches into the engine.
- Public interfaces MUST NOT access Playwright or adapters directly.

### 5.3 Core invariant

The application engine is the only component authorized to operate an authenticated browser session during a run.

---

## 6. Public domain model

### 6.1 Run

A `Run` is the principal execution unit.

Each run MUST contain:

- `run_id`.
- Protocol identifier and version.
- Protocol content hash.
- Validated input values and input hash.
- Browser profile identifier.
- Conversation mode and optional conversation identifier.
- Optional `client_request_id`.
- Effective, sanitized configuration snapshot and hash.
- Exact engine, adapter, rule, schema, hook, and Chromium versions.
- Creation and update timestamps.
- Current public state.
- Immutable execution plan.

Creating a run returns its `run_id` immediately. If the selected profile is occupied, the run enters the profile queue.

### 6.2 Public run states

The public state model is:

```text
queued -> running -> completed
```

Valid exceptional or transitional states include:

- `authentication_required`.
- `recoverable`.
- `cancelling`.
- `cancelled`.
- `failed`.
- `outcome_unknown`.

State transitions MUST be validated and persisted atomically. Invalid transitions MUST fail closed and generate an internal diagnostic event.

### 6.3 Idempotency

`client_request_id` is optional. When supplied, it MUST be scoped by the documented client and request context and MUST prevent accidental creation of a semantically duplicate run.

Idempotency at run creation does not imply that browser actions are freely retryable. Action safety is determined separately from external-effect evidence.

### 6.4 Conversation modes

A protocol may:

- Create a new conversation.
- Continue a known conversation by explicit identifier.
- Import a supported existing conversation through an explicit operation.

Continuation or import MUST NOT be inferred from incidental page state.

### 6.5 Action contract

Every planned action MUST contain:

- A stable `action_id`.
- Action type.
- Validated inputs.
- Preconditions.
- Possible external effects.
- Timeout policy.
- Retry policy.
- Verifiable success condition.
- Recovery strategy.
- Checkpoint eligibility.

Internal action states are:

```text
planned -> started -> confirmed
```

Exceptional results are:

- `retryable_failed`.
- `failed`.
- `cancelled`.
- `outcome_unknown`.

External-effect actions include, at minimum:

- Sending a message.
- Attaching or uploading a file.
- Confirming provider-side actions.
- Downloading an artifact when the provider mutates server-side state.

An action becomes `confirmed` only when the adapter obtains verifiable evidence of its postcondition.

If an interruption occurs after a possible external effect but before confirmation, the action MUST become `outcome_unknown`. It MUST NOT be retried automatically.

### 6.6 Event envelope

Every consumer receives the same versioned event envelope:

- `contract_version`.
- `run_id`.
- `event_id`.
- Monotonic `sequence`.
- UTC `timestamp`.
- `type`.
- Typed `payload`.

Events cover:

- Run lifecycle.
- Queue lifecycle.
- Action lifecycle.
- Response streaming.
- Artifacts.
- Checkpoints.
- Authentication requirements.
- Reconciliation.
- Cancellation.
- Doctor and diagnostics.

Events MUST be persisted before or atomically with publication when loss would make the public state inconsistent.

SSE MUST support reconnection through the last received event identifier. Persisted events MUST allow a client to recover missed events without restarting the run.

### 6.7 Canonical result

The final result MUST be identical in meaning across Python, CLI, and HTTP:

- Canonical block tree.
- Derived Markdown.
- Derived plain text.
- Artifact references and integrity metadata.
- Run and provider metadata.
- Completion classification.
- Relevant warnings and diagnostic references.

The canonical block tree is authoritative. Markdown and plain text are derived representations.

---

## 7. Protocols

### 7.1 Format and versioning

Protocols are declarative documents validated against a versioned schema.

A protocol MUST declare:

- Protocol identifier and version.
- Required engine contract version.
- Required capabilities.
- Input schema.
- Ordered logical operations.
- Explicit checkpoint requests, when needed.
- Typed hook references, when needed.
- Expected output contract.

### 7.2 Supported logical operations

The core protocol vocabulary includes:

- Open or create a conversation.
- Import or continue a conversation.
- Attach files.
- Send a message.
- Wait for and capture a response.
- Download artifacts.
- Execute a typed hook.
- Create a safe checkpoint.
- Produce the final output.

### 7.3 Restrictions

Protocols MUST NOT contain:

- CSS or XPath selectors.
- Provider-specific DOM knowledge.
- Arbitrary JavaScript.
- Arbitrary Python.
- Shell commands.
- Dynamically generated actions derived from provider content.
- Unrestricted navigation targets.

Provider output is untrusted data and MUST NOT modify the immutable execution plan.

---

## 8. Execution engine

### 8.1 Execution lifecycle

The engine performs:

1. Validate protocol and inputs.
2. Resolve adapter, rules, schemas, hooks, and versions.
3. Perform profile and environment preflight.
4. Create and persist an immutable plan.
5. Acquire the profile lock and lease.
6. Start the managed browser runtime.
7. Execute actions in order.
8. Persist events, evidence, artifacts, and safe checkpoints.
9. Reconcile uncertain or interrupted state when required.
10. Produce the final canonical result.
11. Close the browser and release the profile.

### 8.2 Preflight

Before any conversation is opened or modified, preflight MUST validate:

- Engine, protocol, adapter, rule, schema, hook, and Chromium compatibility.
- Profile existence and permissions.
- Profile integrity.
- Recognized authentication state.
- Required input file existence, permissions, size, and type.
- Required provider capabilities.
- Visible or headless execution eligibility.
- Data-root and temporary-directory availability.
- Available disk space.
- SQLite availability and integrity.
- Absence of an active conflicting run.
- Global browser concurrency availability.

A failed preflight MUST NOT modify the provider conversation.

### 8.3 Immutable plan

The execution plan is created before browser actions begin and MUST be immutable for the lifetime of the run.

The plan contains:

- Ordered actions.
- Stable action identifiers.
- Preconditions and postconditions.
- External-effect classifications.
- Retry and timeout policies.
- Recovery rules.
- Checkpoint boundaries.
- Required adapter capabilities.

Any desired change to the intended sequence requires a new run or an explicitly versioned continuation mechanism. Provider content cannot alter the plan.

### 8.4 Retry policy

Only failures classified as `transient` MAY be retried automatically.

Automatic retries MUST:

- Respect a bounded retry count.
- Use documented backoff.
- Re-evaluate the action precondition.
- Avoid repeating a possible external effect.
- Emit action and retry events.

Authentication, adapter mismatch, protocol, environment, fatal, and uncertain-outcome failures MUST NOT be treated as transient.

### 8.5 Cancellation

Cancellation is cooperative:

1. A requested run enters `cancelling`.
2. No new action begins.
3. The active action reaches a safe boundary where possible.
4. Journal and checkpoint state are persisted.
5. Browser resources are closed.
6. The run becomes `cancelled`, `recoverable`, or `outcome_unknown`.

A forced process termination may prevent cooperative cancellation. Recovery then uses the journal and reconciliation flow.

---

## 9. Checkpoints, reconciliation, and resume

### 9.1 Safe checkpoint definition

A checkpoint represents a state from which execution may continue without duplicating an external effect.

It MUST include:

- Last confirmed action.
- Current conversation and message identity.
- Current URL and expected logical page state.
- Exact component versions.
- Protocol and input hashes.
- Produced artifacts.
- Captured canonical block tree to that point.
- Next planned action.
- Relevant postcondition evidence.

### 9.2 Checkpoint boundaries

Checkpoints SHOULD be created:

- After opening or verifying a conversation.
- After confirming a sent message.
- After capturing a complete response.
- After downloading and validating each artifact.
- At explicit protocol checkpoint operations.

A checkpoint MUST NOT be created in the middle of an indivisible external-effect action.

### 9.3 Resume reconciliation

Resume MUST NOT continue blindly from the next stored action.

Before continuing, the engine MUST:

1. Open the same profile and conversation.
2. Verify component versions and identity.
3. Validate current authentication.
4. Compare current page state with checkpoint postconditions.
5. Determine which external effects are demonstrably complete.
6. Confirm a safe next action.

If the conversation changed manually but remains compatible, the engine MAY continue after recording the divergence.

If the engine cannot determine whether an external effect occurred, the run enters `outcome_unknown` and requires explicit intervention.

---

## 10. Failure classification

The engine classifies failures as:

- `transient`: timing, navigation, or temporarily unavailable UI state.
- `authentication`: expired session or required human verification.
- `adapter_mismatch`: provider UI no longer satisfies adapter rules.
- `protocol_error`: invalid inputs, sequence, contract, or unsupported capability.
- `environment`: browser, filesystem, permissions, disk, database, or process issue.
- `outcome_unknown`: a possible external effect cannot be verified.
- `fatal`: internal inconsistency that prevents safe continuation.

Required behavior:

- `transient` MAY retry within policy.
- `authentication` pauses as `authentication_required`.
- `adapter_mismatch` invokes diagnostic capture.
- `protocol_error` fails without modifying additional provider state.
- `environment` becomes `recoverable` when safe recovery is possible.
- `outcome_unknown` never assumes the effect did not occur.
- `fatal` fails closed and captures minimal diagnostic context.

---

## 11. Browser runtime and profiles

### 11.1 Managed Chromium

Cofer U Pass uses only the Chromium build managed and versioned by Playwright.

It MUST NOT:

- Depend on a system Chrome or Edge installation.
- Connect through CDP to arbitrary browsers.
- Disable the Chromium sandbox.
- Install browser extensions.
- Automatically accept invalid certificates.

### 11.2 Persistent profiles

Each profile represents one provider session and account context and contains:

- A dedicated persistent Chromium directory.
- Associated provider and adapter.
- Authentication and health status.
- Compatible Chromium version.
- Visible/headless capability state.
- Related conversation and run records in SQLite.

Cookies and session storage remain inside the profile directory and are never copied into SQLite or diagnostics.

Profile directories MUST use restrictive permissions:

- Windows: restrictive user-only ACL.
- Linux: mode `0700`.

At-rest encryption is delegated to the operating system, such as BitLocker or LUKS.

### 11.3 Authentication

Profile creation and authentication are visible, manual operations:

```text
cofer-u-pass profiles create
cofer-u-pass profiles authenticate <profile>
cofer-u-pass profiles status <profile>
```

The user performs login, MFA, CAPTCHA, consent, and other verification. The adapter only recognizes whether an authenticated application state has been reached.

When a session expires:

1. The run becomes `authentication_required`.
2. Journal and checkpoint state are preserved.
3. No automatic login is attempted.
4. The user reauthenticates the profile visibly.
5. The run is explicitly resumed and reconciled.

### 11.4 Visible and headless modes

Visible mode is the default and is mandatory for authentication or human verification.

Headless execution is allowed only when:

- The adapter declares support.
- The profile is already authenticated.
- The protocol requires no human interaction.
- Preflight confirms that provider signals are reliable in headless mode.

If headless execution encounters MFA, CAPTCHA, consent, authentication, or an unknown screen, it pauses and requires visible recovery.

### 11.5 Profile exclusion

Only one run or process may operate a profile at a time.

Exclusion uses:

- An operating-system lock on the profile directory.
- A SQLite lease containing process identity and heartbeat.
- Conservative stale-lock recovery.

The OS lock is authoritative. The SQLite lease provides observability and diagnosis.

Different profiles may run concurrently, subject to a configurable global browser limit.

### 11.6 Runtime lifecycle

For each run, the runtime:

1. Acquires the profile lock.
2. Validates profile version, permissions, integrity, and authentication.
3. Starts compatible Chromium.
4. Creates only runtime-controlled pages.
5. Executes or reconciles the protocol.
6. Closes Chromium cleanly.
7. Persists final state.
8. Releases lock and lease.

A forced shutdown MUST NOT delete or rebuild the profile. Doctor validates integrity and residual processes before the profile can run again.

### 11.7 Navigation policy

Each adapter declares allowed origins.

Unexpected redirects, unknown domains, authentication pages, consent screens, and security challenges pause execution and generate a diagnostic event.

---

## 12. Adapters and declarative rules

### 12.1 Adapter package

Each adapter contains:

- A trusted Python behavior class.
- A manifest.
- Versioned declarative rules.
- A rule schema version.
- Declared capabilities.
- Compatibility constraints.
- Sanitized DOM fixtures.
- Common contract tests.
- Provider-specific regression tests.

### 12.2 Declarative rules

Rules may define:

- Authentication signals.
- Conversation containers.
- Message input and submission controls.
- Attachment controls.
- Response containers.
- Generation states.
- Completion signals.
- Artifact and download controls.
- Stable identity extraction.

Rules MUST NOT execute Python or JavaScript.

### 12.3 Locator strategy

Elements are resolved in this order:

1. ARIA roles and accessible names.
2. Stable labels and attributes.
3. CSS selectors as a last resort.

A match MUST be unique and satisfy visibility, state, and context assertions.

Ambiguous or contradictory matches stop the action and produce `adapter_mismatch`.

### 12.4 Response state machine

Each provider response follows:

```text
waiting -> streaming -> completed
```

Exceptional terminal states include:

- `interrupted`.
- `moderated`.
- `failed`.

Completion combines:

- Provider-specific signals.
- Visible controls.
- DOM stability.
- A configurable interval without new fragments.

Contradictory signals produce a diagnostic result rather than assumed completion.

### 12.5 DOM streaming

The rendered DOM is the canonical source.

A `MutationObserver` emits structural changes:

- `append`.
- `replace`.
- `remove`.

Periodic full snapshots reconcile missed or ambiguous mutations.

At completion, the adapter MUST:

1. Perform a final reconciliation.
2. Produce the canonical block tree.
3. Compute its content hash.
4. Derive Markdown and plain text.
5. Record discrepancies or unsupported structures.
6. Emit the final completion event.

Network observation MAY be enabled for diagnostics, but MUST NOT become the authoritative output source.

### 12.6 Adapter repair

When a provider UI change breaks an adapter:

1. The stable adapter remains active.
2. Doctor generates a sanitized diagnostic package.
3. Repair work occurs in isolation.
4. The repair adds or updates fixtures.
5. A regression test reproduces the incident.
6. Contract, integration, and affected smoke tests run.
7. The new adapter version is reviewed and explicitly approved.
8. Only then may it be released and activated.

---

## 13. Hooks

Hooks are trusted local Python code installed by the user.

Each hook MUST have:

- A versioned identifier.
- A versioned input and output contract.
- Declared artifact and value access.
- A timeout.
- Input and output size limits.
- A run-specific working directory.

Hooks execute in separate processes with:

- A reduced environment.
- No unnecessary inherited secrets.
- Access only to declared files and values.
- Captured standard output and error.
- Captured exit code.

This isolation reduces accidental damage but is not a security sandbox for hostile Python code. Installing a hook is equivalent to trusting local code execution.

---

## 14. Persistence

### 14.1 SQLite responsibilities

SQLite operates in WAL mode and stores:

- Runs, states, and queues.
- Immutable plans and actions.
- Events and journals.
- Checkpoints and reconciliation data.
- Conversations and messages.
- Canonical block trees.
- Profile metadata and leases.
- Artifact and evidence metadata.
- Installed versions and compatibility data.
- Database migrations and backup records.

SQLite MUST NOT store browser cookies, session storage, passwords, MFA data, or API bearer tokens in plain diagnostic records.

Critical transitions MUST be atomic. Confirming an action, persisting its event, and creating its resulting checkpoint are one logical transaction.

### 14.2 Filesystem responsibilities

The configurable data root separates:

- Persistent browser profiles.
- Downloaded artifacts.
- Diagnostic evidence.
- SQLite backups.
- Local logs.
- Per-run temporary files.

Files are written to a temporary location, validated, and atomically moved into place.

Each artifact stores:

- Content hash.
- Size.
- MIME type.
- Original source.
- `run_id`.
- Producing `action_id`.
- Final local reference.

A run MUST NOT access files from another profile unless the protocol explicitly receives them as inputs.

### 14.3 Migrations

Before a migration:

1. Confirm there are no active runs.
2. Verify SQLite integrity.
3. Create a versioned, timestamped backup.
4. Apply the migration transactionally where possible.
5. Validate schema and functional invariants.

If validation fails, the new version MUST NOT start. The backup and documented restoration path remain available.

There are no silent destructive migrations or uncertain automatic downgrades.

### 14.4 Retention

Retention is independently configurable for:

- Logs and events.
- Diagnostic evidence.
- Backups.
- Artifacts.
- Completed runs.

Cleanup is explicit and conservative. It MUST NOT remove:

- Browser profiles.
- Imported conversations.
- Recent required backups.
- Artifacts referenced by retained runs.
- Evidence required by an unresolved incident.

---

## 15. Doctor and diagnostic evidence

### 15.1 Preventive Doctor

```text
cofer-u-pass doctor
```

Preventive checks cover:

- Installation.
- Configuration.
- SQLite integrity and migrations.
- Filesystem permissions.
- Data-root capacity.
- Chromium installation and compatibility.
- Profile integrity and authentication state.
- Locks, leases, and residual processes.
- Adapter and schema compatibility.
- Loopback API security.

### 15.2 Reactive Doctor

Reactive diagnosis is triggered by:

- `adapter_mismatch`.
- Reproducible browser inconsistencies.
- Internal invariant failures.
- Selected environment failures.
- Uncertain recovery state where evidence can assist a human.

### 15.3 Diagnostic package

A package MAY include:

- Failed adapter rule and evaluated locators.
- Expected and observed logical state.
- Relevant sanitized DOM fragment.
- Redacted screenshot when needed.
- Relevant event and journal interval.
- Component versions and platform.
- Non-secret effective configuration.
- Minimal reproduction steps.
- Sanitized network diagnostics when explicitly enabled.

It MUST NOT include:

- Cookies or browser session storage.
- Browser profile contents.
- Local API tokens.
- Passwords, MFA data, or authentication codes.
- Authorization headers.
- Sensitive request or response bodies.
- Complete unrelated conversations.
- Unrelated user files.

Before export, the user receives an inventory and can inspect the package.

Packages contain a manifest, schema version, and hashes. There is no automatic upload.

---

## 16. Security and trust model

### 16.1 Deployment model

v1 is a local, single-operating-system-user application.

It is not designed as:

- A remote server.
- A shared service.
- A multi-user application.
- A multi-tenant platform.

### 16.2 Trust boundaries

- The engine, installed adapters, approved protocols, and installed hooks are trusted local components.
- DOM content, provider output, downloaded files, and generated text are untrusted data.
- Declarative rules may locate and extract data but may not execute code.
- Hooks are trusted code and are not safe to install from untrusted sources.

Provider content MUST NEVER create new actions, alter the execution plan, invoke hooks, read undeclared files, or execute commands.

### 16.3 Local API

The HTTP service:

- Listens only on `127.0.0.1` and `::1`.
- Has no v1 configuration that exposes it remotely.
- Requires a random token generated by `setup`.
- Accepts the token only through `Authorization: Bearer`.
- Never accepts the token in URLs.
- Applies restrictive CORS.
- Redacts tokens and sensitive values from logs and diagnostics.
- Supports explicit token rotation.

TLS, remote exposure, tunnels, firewall publication, and multi-user authentication are outside v1.

### 16.4 Browser security

Chromium:

- Runs without administrative privileges.
- Retains its sandbox.
- Navigates only to adapter-declared origins.
- Pauses at unknown domains or verification screens.
- Does not install extensions.
- Does not automatically accept insecure certificates.
- Does not execute protocol-supplied JavaScript.

### 16.5 File security

All paths are normalized and validated.

The implementation MUST prevent:

- `..` path traversal.
- Symlink escapes.
- Provider-controlled absolute paths.
- Unsafe filenames.
- Downloads outside the run directory.
- Automatic execution or opening of downloaded files.

Inputs and downloads have configurable type and size limits.

### 16.6 Explicit protection limit

Cofer U Pass protects against operational mistakes, accidental API exposure, malicious web content, and duplicate external actions.

It cannot protect profiles or tokens from:

- Malware.
- Another process running as the same operating-system user.
- A compromised machine.
- A person with access to the same account and storage.

Endpoint security, account separation, filesystem permissions, and disk encryption remain operating-system responsibilities.

---

## 17. Configuration

### 17.1 Canonical format

Configuration is canonical TOML validated by a versioned schema.

Precedence is:

1. Explicit CLI or API options.
2. Documented environment variables.
3. Profile configuration.
4. Global configuration.
5. Secure defaults.

Not every value may be overridden per run.

Global-only security settings include:

- Allowed origins.
- Data root.
- API binding.
- Hook resource policies.
- Security limits.
- Diagnostic redaction policies.

### 17.2 Commands

```text
cofer-u-pass config paths
cofer-u-pass config validate
cofer-u-pass config show --effective
cofer-u-pass config show --effective --profile <profile>
```

Effective configuration output redacts secrets by default.

Each run retains:

- A hash of effective configuration.
- A sanitized configuration snapshot.

### 17.3 Required configuration areas

The schema MUST cover:

- Data and temporary paths.
- Database settings.
- Logging.
- Retention.
- Global browser concurrency.
- Visible/headless defaults.
- Timeouts and bounded retries.
- Profile-specific provider options.
- Artifact size and type limits.
- Hook limits.
- API token reference and CORS.
- Doctor evidence and redaction.
- Network diagnostics opt-in.

The exact keys and defaults MUST be documented in `RUNBOOK.md` and covered by schema tests.

---

## 18. Public interfaces

### 18.1 Python library

The Python API is asynchronous.

Creating or resolving a run returns a `RunHandle` that supports:

- Inspecting current state.
- Iterating events.
- Awaiting completion.
- Requesting cancellation.
- Requesting resume.
- Accessing the canonical result.
- Accessing artifact and diagnostic references.

The library MUST NOT require the caller to know Playwright or provider DOM details.

### 18.2 CLI

The CLI exposes the same application use cases. Planned command families include:

```text
cofer-u-pass setup
cofer-u-pass doctor
cofer-u-pass serve
cofer-u-pass run
cofer-u-pass status
cofer-u-pass stream
cofer-u-pass cancel
cofer-u-pass resume
cofer-u-pass import-conversation
cofer-u-pass profiles ...
cofer-u-pass config ...
cofer-u-pass update ...
```

CLI output MUST support a human-readable default and a documented machine-readable mode.

### 18.3 HTTP API and SSE

The API is versioned under:

```text
/api/v1/
```

The run resource family MUST support:

- Create run.
- Get run.
- Get current status.
- Stream events through SSE.
- Request cancellation.
- Request resume.
- Retrieve the canonical result.
- List or retrieve artifact metadata.
- Retrieve allowed diagnostic metadata.

The exact endpoint and payload schemas MUST be generated or validated from the shared contracts.

SSE reconnection MUST use persisted event identifiers and maintain event ordering.

---

## 19. Installation and operation

### 19.1 Distribution

Cofer U Pass is distributed as one Python package containing:

- Library.
- CLI.
- Local API.
- Official adapters.
- Schemas.
- Required static resources.

Canonical installation:

```text
uv tool install cofer-u-pass
pipx install cofer-u-pass
```

Version pinning and prereleases are supported:

```text
uv tool install cofer-u-pass==1.0.0
uv tool install --prerelease allow cofer-u-pass
```

### 19.2 Setup

```text
cofer-u-pass setup
cofer-u-pass setup --dry-run
```

`setup` is idempotent and MUST:

- Create required directories with appropriate permissions.
- Create initial TOML configuration.
- Generate the local API token.
- Initialize SQLite and apply migrations.
- Install compatible Chromium through Playwright.
- Run basic validation.
- Show explicit next steps.

Re-running setup MUST NOT delete profiles, runs, artifacts, or user configuration.

`--dry-run` reports intended changes without applying them.

### 19.3 Service lifecycle

Primary foreground operation:

```text
cofer-u-pass serve
```

On the first interrupt:

1. Stop accepting new runs.
2. Preserve queued runs.
3. Request safe cancellation of active runs.
4. Persist journals and checkpoints.
5. Close Chromium.
6. Release locks.

A second interrupt may force exit. Affected runs are classified as `recoverable` or `outcome_unknown` based on their last action.

Optional user-level background operation MAY be documented for:

- `systemd --user` on Linux.
- Windows Task Scheduler.

Installation MUST NOT require administrative privileges or silently create an OS service.

### 19.4 Updates

Updates are explicit:

```text
cofer-u-pass update --check
cofer-u-pass update
```

Before updating, the tool MUST verify:

- No active runs.
- Configuration compatibility.
- Database compatibility and integrity.
- Chromium and profile compatibility.
- Available disk space.
- Ability to create a recoverable backup.

If migration is required, the command displays the versions and backup location before mutation.

### 19.5 Rollback

Package rollback is possible by installing a pinned version.

If the database schema is incompatible with the older version, the matching backup MUST be restored. The system MUST NOT attempt an uncertain automatic reverse migration.

---

## 20. RUNBOOK.md requirements

`RUNBOOK.md` is a mandatory v1 deliverable, not an optional appendix.

It MUST be operational, self-contained, verified on Windows and Linux, and organized as follows:

1. Supported platforms and prerequisites.
2. Installation with `uv tool` and `pipx`.
3. Setup, created directories, and permissions.
4. Complete TOML configuration reference.
5. Environment variables and precedence.
6. Profile creation, authentication, inspection, and maintenance.
7. CLI execution.
8. Python library usage.
9. HTTP API and SSE usage.
10. Foreground and optional user-level service operation.
11. Protocols, hooks, and adapters.
12. Artifacts, logs, and evidence.
13. Backups, migrations, and rollback.
14. Cancellation, resume, and reconciliation.
15. Lock and interrupted-process recovery.
16. `authentication_required` recovery.
17. `outcome_unknown` investigation and resolution.
18. Preventive and reactive Doctor usage.
19. Provider smoke tests.
20. Updates, prereleases, and version pinning.
21. Retention, cleanup, and uninstall.
22. Troubleshooting by symptom, likely cause, and verified command.

Every procedure MUST include:

- Bash examples.
- PowerShell examples.
- Expected result.
- Preconditions.
- Warnings for actions that may affect data.
- A recovery or rollback path where applicable.

Commands MUST be tested rather than copied from assumptions.

---

## 21. Testing strategy

### 21.1 Test pyramid

The required strategy combines:

- Deterministic unit tests.
- Sanitized DOM fixtures.
- Shared adapter contract tests.
- Chromium integration tests against controlled local sites.
- Migration tests.
- Installed-wheel validation.
- Manual supervised provider smoke tests.

### 21.2 Unit tests

Unit coverage includes:

- State machines.
- Protocol validation.
- Plan immutability.
- Action idempotency rules.
- Event ordering.
- Streaming reconciliation.
- Canonical block generation.
- Journal and checkpoint behavior.
- Cancellation.
- Failure classification.
- Configuration precedence.
- Path security.
- Sanitization.
- Retention selection.

### 21.3 Contract tests

All adapters, including `generic`, run against a common contract that validates:

- Capability declarations.
- Authentication recognition.
- Locator uniqueness.
- Conversation operations.
- Submission confirmation.
- Response state transitions.
- Streaming events.
- Canonical output.
- Artifact handling.
- Failure classification.
- Evidence sanitization.

### 21.4 Fixtures and regression tests

Sanitized HTML/DOM fixtures reproduce:

- Expected provider states.
- Streaming mutations.
- Completion signals.
- Moderation and interruption.
- Authentication expiration.
- Consent and CAPTCHA screens.
- Ambiguous locator failures.
- UI changes that caused production incidents.

Every Doctor-driven adapter repair MUST add a regression test.

### 21.5 Chromium integration

Integration tests use real managed Chromium against local controlled sites to validate:

- Persistent profile lifecycle.
- Locks and leases.
- Visible/headless rules.
- Navigation restrictions.
- DOM observation.
- File upload and download.
- SSE recovery.
- Cooperative and forced shutdown behavior.

### 21.6 Provider smoke tests

ChatGPT, Gemini, and DeepSeek smoke tests:

- Use manually authenticated profiles.
- Run under human supervision.
- Never run in CI.
- Never store credentials.
- Validate affected provider functionality before a stable release.

### 21.7 Platform matrix

Official release validation covers documented supported versions of:

- Windows.
- Linux.
- Python.
- Playwright-managed Chromium.

The exact matrix is published with each release.

---

## 22. Release policy

Semantic Versioning applies:

- `PATCH`: compatible fixes, including adapter repairs.
- `MINOR`: compatible capabilities.
- `MAJOR`: incompatible API, configuration, or contract changes.

A release candidate uses an `rc` version.

A stable release requires:

- Passing unit tests.
- Passing adapter contract tests.
- Passing fixture and regression tests.
- Passing Chromium integration tests.
- Passing migrations from all supported versions.
- Successful installation and validation from the built wheel.
- Passing Windows and Linux matrix.
- Passing supervised smoke tests for affected providers.
- Complete documentation and runbook review.
- Secret and sensitive-evidence scanning.
- Explicit release approval.

Passing CI alone MUST NOT automatically publish a stable release.

Release artifacts include:

- Wheel.
- Source distribution.
- Hashes.
- Changelog.
- Compatibility matrix.
- Migration notes.

Deprecations remain for at least one minor version and include warnings and documented migration paths.

No component updates silently during an active run.

---

## 23. Repository structure

```text
cofer-u-pass/
├── pyproject.toml
├── src/
│   └── cofer_u_pass/
│       ├── domain/
│       ├── application/
│       ├── protocols/
│       ├── browser/
│       ├── adapters/
│       │   ├── generic/
│       │   ├── chatgpt/
│       │   ├── gemini/
│       │   └── deepseek/
│       ├── persistence/
│       ├── hooks/
│       ├── doctor/
│       ├── config/
│       ├── api/
│       ├── cli/
│       └── library/
├── schemas/
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   ├── migrations/
│   ├── fixtures/
│   └── smoke/
├── examples/
├── docs/
│   ├── architecture/
│   ├── protocols/
│   ├── adapters/
│   ├── api/
│   ├── SECURITY.md
│   └── RUNBOOK.md
└── scripts/
```

The exact internal filenames may evolve, but the dependency boundaries and responsibility separation are normative.

---

## 24. Implementation increments

Implementation proceeds through usable, tested increments.

### Increment 1 — Domain and contracts

- Domain types and states.
- Protocol and configuration schemas.
- Canonical block contract.
- Public event contract.
- Compatibility model.
- Initial Python API surface.

Exit criteria:

- Schemas validate representative examples.
- State and contract unit tests pass.
- Dependency boundaries are enforceable.

### Increment 2 — Persistence and recovery core

- SQLite repositories and migrations.
- Runs, plans, actions, events, and journals.
- Checkpoints.
- Queue semantics.
- Cancellation and reconciliation foundation.
- Filesystem artifact store.

Exit criteria:

- Atomic invariants are tested.
- Restart and recovery simulations pass.
- Migration and backup tests pass.

### Increment 3 — Browser runtime and generic adapter

- Playwright-managed Chromium lifecycle.
- Persistent profiles.
- Authentication recognition contract.
- OS locks and SQLite leases.
- Navigation policy.
- `generic` adapter.
- Controlled local integration site.

Exit criteria:

- Profile isolation and recovery tests pass.
- DOM streaming works in controlled integration tests.
- External-effect uncertainty is handled safely.

### Increment 4 — Public interfaces and hooks

- Complete asynchronous Python library.
- CLI.
- HTTP v1 and SSE.
- Typed hook execution.
- Cross-interface equivalence tests.

Exit criteria:

- The same protocol produces equivalent results through all interfaces.
- SSE reconnection and missed-event recovery pass.
- Hook limits and failure behavior pass.

### Increment 5 — Official provider adapters

- ChatGPT.
- Gemini.
- DeepSeek.
- Fixtures and regression suites.
- Artifact and attachment capabilities.

Exit criteria:

- Common adapter contracts pass.
- Supervised provider smoke tests pass.
- Provider limitations are documented.

### Increment 6 — Doctor, packaging, and hardening

- Preventive and reactive Doctor.
- Sanitized diagnostic packages.
- Update and rollback workflow.
- Wheel and source distribution.
- Security review.
- Complete documentation.
- Verified `RUNBOOK.md`.

Exit criteria:

- Installed-wheel validation passes.
- Windows/Linux release matrix passes.
- Diagnostic sanitization is verified.
- All v1 acceptance criteria pass.

Each increment MUST finish with tests and documentation. Validation MUST NOT be deferred entirely to the final increment.

---

## 25. Integral acceptance criteria

v1 is accepted only when a clean installation can:

1. Install from its wheel with `uv tool` and `pipx`.
2. Run `setup` and `doctor` without hidden manual steps.
3. Create and manually authenticate a profile.
4. Execute the same protocol through Python, CLI, and HTTP.
5. Emit equivalent events and return the same canonical result across interfaces.
6. Send messages and attachments.
7. Capture faithful response streaming.
8. Download and validate artifacts.
9. Stop and resume from a demonstrably safe checkpoint.
10. Avoid automatically repeating every uncertain external effect.
11. Pause correctly for authentication, CAPTCHA, consent, or an unknown domain.
12. Generate a sanitized diagnostic package for a reproducible UI change.
13. Prevent simultaneous execution on the same profile.
14. Allow controlled parallelism across different profiles.
15. Update the database only after validation and backup.
16. Restore a documented backup when rollback requires it.
17. Pass unit, contract, fixture, integration, migration, and installed-wheel tests.
18. Pass supervised smoke tests for all official providers.
19. Pass the supported Windows and Linux matrix.
20. Keep the API restricted to loopback.
21. Avoid secret leakage in logs, events, and evidence.
22. Provide a complete and verified `RUNBOOK.md`.

No arbitrary performance guarantees are part of v1. The release SHOULD publish reproducible measurements of internal latency, resource consumption, and stability as a baseline for future service objectives.

---

## 26. Primary risks and required mitigations

| Risk | Required mitigation |
| --- | --- |
| Provider UI changes | Versioned adapters, declarative rules, sanitized fixtures, Doctor packages, regression tests, supervised smoke tests |
| Duplicate message or external action | Confirmed postconditions, immutable actions, checkpoints, reconciliation, `outcome_unknown` |
| Corrupted persistent profile | Exclusive OS lock, lease visibility, orderly shutdown, Doctor integrity checks, no automatic rebuild |
| Expired authentication | Manual visible reauthentication, preserved checkpoint, explicit resume |
| Lost streaming mutations | Mutation events plus periodic full DOM reconciliation |
| Secret leakage | Local-only operation, redaction, evidence allowlists, export inventory, no telemetry |
| Unsafe downloaded content | Constrained paths, size/type limits, hashing, no automatic opening or execution |
| Incompatible update | Preflight, backup, migration validation, explicit rollback |
| Divergent public interfaces | Shared application service and cross-interface contract tests |
| Untrusted provider instructions | Immutable plan and strict separation between content and actions |
| Hostile hook | Trusted-code warning, separate process, reduced environment, bounded access; no claim of a security sandbox |
| Accidental remote API exposure | Hard loopback binding, bearer token, restrictive CORS, no v1 remote-bind option |

---

## 27. Required follow-up artifacts

Before implementation is considered complete, the repository MUST contain:

- Versioned protocol schema and examples.
- Versioned event schema.
- Canonical block schema.
- Adapter manifest and rule schemas.
- Configuration schema and complete default reference.
- Public Python API documentation.
- HTTP/OpenAPI and SSE contract documentation.
- Architecture decision records for irreversible or high-impact choices.
- `SECURITY.md`.
- `RUNBOOK.md`.
- Provider compatibility matrix.
- Release and migration notes.

This specification is the approved product and architectural baseline. Material scope changes require an explicit design decision and specification update before implementation.
