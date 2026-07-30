# Model catalog and ChatGPT inference runbook — v1.2

This runbook covers the Stage 1 model catalog and the supervised validation of `model + reasoning.effort` against ChatGPT Web.

The catalog is derived data. Browser authentication/profile state remains authoritative and is never stored in the catalog.

## 1. Inspect profile state

Git Bash:

```bash
cofer-u-pass profiles status chatgpt-main --verify
```

Expected:

- `provider` is `chatgpt`;
- `status` is `ready`;
- `authenticated` is `true`.

If authentication is required:

```bash
cofer-u-pass profiles authenticate chatgpt-main
```

Complete password/MFA/CAPTCHA manually in the managed Chromium window. U Pass does not automate those steps.

A successful CLI authentication attempts a best-effort catalog refresh. A catalog-discovery failure does not undo successful authentication.

## 2. Inspect the cached model catalog

```bash
cofer-u-pass profiles models chatgpt-main
```

A valid snapshot contains:

- `profile_id`;
- `provider`;
- `updated_at`;
- `error: null`;
- one or more `models`;
- each model's public `id`, display name, and discovered `supported_efforts`.

If the catalog has not been discovered, the command reports that a refresh is required.

If `error` is non-null, treat the catalog as invalid; stale models are not served as current models.

## 3. Explicitly refresh the catalog

```bash
cofer-u-pass profiles models chatgpt-main --refresh
```

This may open visible managed Chromium because the ChatGPT adapter is not declared headless-safe.

Expected:

- ChatGPT opens authenticated;
- U Pass opens the model/intelligence controls without sending a message;
- model entries are discovered;
- the original model/intelligence state is restored when possible;
- the command returns a snapshot with `error: null`.

On failure:

1. do not delete the profile;
2. run `cofer-u-pass profiles models chatgpt-main` to inspect the persisted error;
3. run `cofer-u-pass doctor`;
4. inspect ChatGPT Web manually to determine whether the picker DOM/labels changed;
5. do not bypass inference verification or hardcode a fallback model.

## 4. Verify the local `/v1/models` catalog

Start the service in one Git Bash terminal:

```bash
cofer-u-pass serve
```

In another Git Bash terminal:

```bash
DATA_ROOT=$(cofer-u-pass config paths | python -c "import json,sys; print(json.load(sys.stdin)['data_root'])")
TOKEN=$(cat "$DATA_ROOT/secrets/api-token")

curl -s \
  -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8765/v1/models \
  | python -m json.tool
```

Expected:

- real discovered model ids are returned;
- `chatgpt-main` is not advertised as the preferred model id;
- ChatGPT model metadata includes `reasoning_efforts`;
- a model with multiple routing candidates is marked ambiguous rather than silently routed.

Choose one advertised ChatGPT model and one advertised effort for the next steps.

## 5. Send a real model + effort request

Set values from `/v1/models`:

```bash
MODEL='REPLACE_WITH_DISCOVERED_MODEL_ID'
EFFORT='REPLACE_WITH_ADVERTISED_EFFORT'
```

Then:

```bash
curl -s \
  -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8765/v1/responses \
  -d "{\"model\":\"$MODEL\",\"reasoning\":{\"effort\":\"$EFFORT\"},\"input\":\"Respond exactly with: COFER_U_PASS_MODEL_EFFORT_OK\"}" \
  | tee /tmp/cofer-u-pass-stage1-response.json \
  | python -m json.tool
```

Expected:

- response status is `completed`;
- output contains `COFER_U_PASS_MODEL_EFFORT_OK`;
- `metadata.cofer_effective_model` equals `$MODEL`;
- `metadata.cofer_effective_effort` equals `$EFFORT`.

The effective metadata is populated from the verified `configure_inference` action evidence. The response text by itself is not proof that the requested model/intelligence state was used.

## 6. Run the supervised pytest smoke

Stop `cofer-u-pass serve` first so the profile is not locked by another process.

From the repository checkout:

```bash
export COFER_U_PASS_SMOKE_PROFILE='chatgpt-main'
export COFER_U_PASS_SMOKE_PROVIDER='chatgpt'
export COFER_U_PASS_SMOKE_MODEL="$MODEL"
export COFER_U_PASS_SMOKE_EFFORT="$EFFORT"

pytest -m smoke tests/smoke/test_providers.py -k model_effort -q
```

Expected: one Stage 1 model/effort smoke test passes. The test asserts both exact response content and the effective model/effort evidence.

## 7. Test a second effort on the same model

Pick a different effort advertised for the same model and repeat steps 5–6.

This is the preferred Stage 1 acceptance test because it demonstrates that the web intelligence control is actually being changed while the model remains constant.

## 8. Fail-closed negative test

With the service running again, send a public but unadvertised effort for the selected model, for example only if that effort is absent from the model's catalog:

```bash
BAD_EFFORT='REPLACE_WITH_VALID_PUBLIC_BUT_UNADVERTISED_EFFORT'

curl -i \
  -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8765/v1/responses \
  -d "{\"model\":\"$MODEL\",\"reasoning\":{\"effort\":\"$BAD_EFFORT\"},\"input\":\"THIS MUST NOT BE SENT\"}"
```

Expected: request fails with a client/contract error and **no ChatGPT message containing `THIS MUST NOT BE SENT` appears**.

Also verify an invalid public effort is rejected without browser execution:

```bash
curl -i \
  -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8765/v1/responses \
  -d "{\"model\":\"$MODEL\",\"reasoning\":{\"effort\":\"banana\"},\"input\":\"THIS MUST NOT BE SENT\"}"
```

## 9. Legacy compatibility check

The v1.1 profile-id alias remains accepted when no effort is requested:

```bash
curl -s \
  -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8765/v1/responses \
  -d '{"model":"chatgpt-main","input":"Respond exactly with: COFER_U_PASS_LEGACY_OK"}' \
  | python -m json.tool
```

Expected: the request can complete using the provider's current/default inference state.

The legacy alias must reject an explicit effort:

```bash
curl -i \
  -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8765/v1/responses \
  -d '{"model":"chatgpt-main","reasoning":{"effort":"high"},"input":"THIS MUST NOT BE SENT"}'
```

Expected: client/contract error, with no message sent.

## 10. Stage 1 acceptance report

Record these results before beginning Stage 2:

```text
Profile status: PASS/FAIL
Catalog refresh: PASS/FAIL
/v1/models real models: PASS/FAIL
Model + effort request #1: PASS/FAIL
Model + effort request #2, same model: PASS/FAIL
Effective model evidence: PASS/FAIL
Effective effort evidence: PASS/FAIL
Unsupported effort fail-closed: PASS/FAIL
Invalid effort fail-closed: PASS/FAIL
Legacy profile alias without effort: PASS/FAIL
Legacy profile alias with effort rejected: PASS/FAIL
Observed ChatGPT model ids:
Observed effort values:
Notes / UI mismatches:
```

Do not proceed to Stage 2 while any model/effort selection or fail-closed check remains unresolved.
