# Restricted Provider Exchange — v1.1

Cofer U Pass can expose an authenticated web profile as a restricted text/file model. This is intentionally **not** tool emulation: `tools`, function calling, and non-`none` `tool_choice` are rejected.

## Capabilities

The provider supports text input/output, Files-API uploads, input bundles, downloadable provider files, and validated ZIP bundles. Streaming is currently buffered. Tool/function-calling semantics are unsupported by contract.

## Local API

Start the local service with `cofer-u-pass serve`. Its OpenAI-compatible exchange surface is:

- `GET /v1/models`
- `GET /v1/models/{profile}/capabilities`
- `POST /v1/files`
- `GET /v1/files/{file_id}`
- `GET /v1/files/{file_id}/content`
- `DELETE /v1/files/{file_id}`
- `POST /v1/responses`

All endpoints retain the normal Cofer U Pass loopback bearer-token policy.

A plain text response requires no exchange protocol. For file/bundle output, use the minimal `cofer-u-pass.exchange/1` contract. The task/role remains entirely in the prompt.

```json
{
  "schema": "cofer-u-pass.exchange/1",
  "input": {"strategy": "auto"},
  "output": {
    "kind": "bundle",
    "filename": "architecture.zip",
    "required_files": ["SPEC.md"],
    "optional_files": ["DECISIONS.md"],
    "allow_extra_files": true
  }
}
```

For a small protocol, pass compact JSON as a **string** in `metadata.cofer_protocol`. For larger protocols, upload the JSON through `/v1/files` and pass its ID in `metadata.cofer_protocol_file`.

Input ZIPs are treated as untrusted data. Cofer U Pass rejects path traversal, absolute paths, symlink/special entries, nested archives, excessive depth/entry count, per-file limits, and excessive expanded size. Provider-generated ZIP bundles are validated again before success is returned.

## Cofer One IA worker

Cofer One IA keeps a Docker bridge separate from Chromium. The host worker initiates the connection outward, so the normal Cofer U Pass API remains loopback-only and browser profiles/cookies never enter Docker.

Git Bash:

```bash
export COFER_U_PASS_BRIDGE_KEY='<same value as cofer-one-ia/.env>'
cofer-u-pass worker \
  --bridge http://127.0.0.1:4011 \
  --profile chatgpt-main
```

The worker registers the selected authenticated profiles, long-polls for jobs, keeps a heartbeat during long browser execution, streams request/output files in bounded chunks, and uploads provider artifacts back to the bridge.

If the worker disappears while a job is leased, that job must not be replayed blindly: an external message may already have been submitted. The bridge is expected to fail closed and surface an uncertain external outcome instead of automatically duplicating the work.
