# Protocols

Protocols are YAML, JSON, or TOML documents validated as `ProtocolDefinition` plus JSON Schema input validation. Provider selectors, arbitrary JavaScript/Python, shell commands, and provider-derived dynamic actions are prohibited.

Supported operations:

- `open_conversation`
- `attach_files`
- `send_message`
- `capture_response`
- `download_artifacts`
- `hook`
- `checkpoint`
- `finalize`

Input references use whole-value substitution such as `${input.prompt}` or `${input.files}`. Provider output never expands the immutable plan.

See `examples/ask.yaml` and `examples/ask-with-files.yaml`.
