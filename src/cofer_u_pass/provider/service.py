from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cofer_u_pass.application.service import ApplicationService
from cofer_u_pass.domain.errors import ProtocolError
from cofer_u_pass.domain.models import ConversationMode, ProtocolDefinition, ProtocolOperation, RunState
from cofer_u_pass.exchange.models import ExchangeProtocol
from cofer_u_pass.exchange.normalizer import NormalizedInputs, normalize_input_files, validate_output_bundle
from cofer_u_pass.provider.files import ProviderFileStore


@dataclass(slots=True)
class CompiledRequest:
    model: str
    prompt: str
    input_paths: list[Path]
    protocol: ExchangeProtocol
    stream: bool
    client_request_id: str | None


class RestrictedProviderService:
    """Translate an OpenAI Responses-style request into a safe Cofer U Pass run.

    This provider intentionally supports text/file exchange only. Tool calls are
    rejected instead of being silently ignored or emulated through the web UI.
    """

    def __init__(self, service: ApplicationService, files: ProviderFileStore | None = None):
        self.service = service
        self.files = files or ProviderFileStore(service.config)

    async def model_capabilities(self, profile_id: str) -> dict[str, Any]:
        profile = await self.service.profile_status(profile_id, verify=False)
        adapter = self.service.registry.create(profile.provider)
        capabilities = adapter.capabilities
        return {
            "model": profile_id,
            "provider": profile.provider,
            "profile_status": profile.status,
            "capabilities": {
                "text_input": True,
                "text_output": True,
                "file_input": "attachment.upload" in capabilities,
                "file_output": "artifact.download" in capabilities,
                "bundle_input": True,
                "bundle_output": "artifact.download" in capabilities,
                "streaming": "buffered",
                "tools": False,
                "function_calling": False,
            },
            "exchange_protocol": "cofer-u-pass.exchange/1",
        }

    async def list_models(self) -> list[dict[str, Any]]:
        items = []
        for profile in await self.service.list_profiles():
            caps = await self.model_capabilities(profile.profile_id)
            items.append({
                "id": profile.profile_id,
                "object": "model",
                "created": 0,
                "owned_by": f"cofer-u-pass:{profile.provider}",
                "metadata": {"cofer_capabilities": caps["capabilities"]},
            })
        return items

    def _parse_protocol(
        self,
        metadata: dict[str, Any] | None,
        *,
        resolved_files: dict[str, Path] | None = None,
    ) -> ExchangeProtocol:
        values = metadata or {}
        raw = values.get("cofer_protocol")
        protocol_file_id = values.get("cofer_protocol_file")
        if raw not in {None, ""} and protocol_file_id not in {None, ""}:
            raise ProtocolError("use either metadata.cofer_protocol or metadata.cofer_protocol_file, not both")
        if protocol_file_id not in {None, ""}:
            if not isinstance(protocol_file_id, str) or not protocol_file_id.startswith("file-"):
                raise ProtocolError("metadata.cofer_protocol_file must be a file-* ID")
            resolved = resolved_files or {}
            try:
                path = resolved.get(protocol_file_id) or self.files.content_path(protocol_file_id)
            except KeyError as exc:
                raise ProtocolError(f"unknown protocol file_id: {protocol_file_id}") from exc
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProtocolError(f"cofer protocol file is not valid UTF-8 JSON: {exc}") from exc
        if raw is None or raw == "":
            return ExchangeProtocol()
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ProtocolError(f"metadata.cofer_protocol is not valid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise ProtocolError("metadata.cofer_protocol must be a JSON object/string or use cofer_protocol_file")
        try:
            return ExchangeProtocol.model_validate(raw)
        except Exception as exc:
            raise ProtocolError(f"invalid cofer exchange protocol: {exc}") from exc

    def _extract_input(self, body: dict[str, Any]) -> tuple[str, list[str]]:
        instructions = body.get("instructions")
        if instructions is not None and not isinstance(instructions, str):
            raise ProtocolError("instructions must be a string")
        input_value = body.get("input", "")
        text_parts: list[str] = []
        file_ids: list[str] = []
        if instructions:
            text_parts.append(f"INSTRUCTIONS:\n{instructions.strip()}")

        if isinstance(input_value, str):
            if input_value.strip():
                text_parts.append(input_value.strip())
            return "\n\n".join(text_parts), file_ids
        if not isinstance(input_value, list):
            raise ProtocolError("input must be a string or a Responses-style list")

        for item in input_value:
            if not isinstance(item, dict):
                raise ProtocolError("input items must be objects")
            item_type = item.get("type")
            if item_type in {"function_call", "function_call_output", "computer_call", "computer_call_output"}:
                raise ProtocolError(f"unsupported agent/tool input item: {item_type}")
            if item_type not in {None, "message"}:
                # Some clients send content parts directly at the top level.
                content = [item]
                role = "user"
            else:
                content = item.get("content", [])
                role = str(item.get("role") or "user")
                if isinstance(content, str):
                    content = [{"type": "input_text", "text": content}]
            if not isinstance(content, list):
                raise ProtocolError("message content must be a list or string")
            role_text: list[str] = []
            for part in content:
                if isinstance(part, str):
                    role_text.append(part)
                    continue
                if not isinstance(part, dict):
                    raise ProtocolError("content parts must be objects")
                part_type = part.get("type")
                if part_type in {"input_text", "text", "output_text"}:
                    value = part.get("text")
                    if isinstance(value, str) and value:
                        role_text.append(value)
                elif part_type == "input_file":
                    file_id = part.get("file_id")
                    if not isinstance(file_id, str) or not file_id:
                        raise ProtocolError("input_file requires file_id; upload through /v1/files first")
                    file_ids.append(file_id)
                elif part_type == "input_image":
                    file_id = part.get("file_id")
                    if not isinstance(file_id, str) or not file_id:
                        raise ProtocolError("input_image currently requires file_id")
                    file_ids.append(file_id)
                else:
                    raise ProtocolError(f"unsupported content part: {part_type}")
            if role_text:
                label = role.upper() if role in {"system", "developer", "assistant"} else "USER"
                text_parts.append(f"{label}:\n" + "\n".join(role_text))
        return "\n\n".join(text_parts).strip(), file_ids

    def compile_request(self, body: dict[str, Any], *, resolved_files: dict[str, Path] | None = None) -> CompiledRequest:
        if not isinstance(body, dict):
            raise ProtocolError("request body must be a JSON object")
        metadata = body.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            raise ProtocolError("metadata must be a JSON object")
        if body.get("tools"):
            raise ProtocolError("cofer-u-pass web models do not support tools or function calling")
        if body.get("tool_choice") not in {None, "none"}:
            raise ProtocolError("cofer-u-pass web models do not support tool_choice")
        model = body.get("model")
        if not isinstance(model, str) or not model:
            raise ProtocolError("model is required and must be a Cofer U Pass profile id")
        prompt, file_ids = self._extract_input(body)
        if not prompt and not file_ids:
            raise ProtocolError("request has no text or file input")
        paths: list[Path] = []
        resolved = resolved_files or {}
        for file_id in file_ids:
            try:
                paths.append(resolved[file_id] if file_id in resolved else self.files.content_path(file_id))
            except KeyError as exc:
                raise ProtocolError(f"unknown input file_id: {file_id}") from exc
        protocol = self._parse_protocol(metadata, resolved_files=resolved)
        return CompiledRequest(
            model=model,
            prompt=prompt,
            input_paths=paths,
            protocol=protocol,
            stream=bool(body.get("stream", False)),
            client_request_id=body.get("client_request_id") or (metadata or {}).get("client_request_id"),
        )

    @staticmethod
    def _output_instruction(protocol: ExchangeProtocol) -> str:
        output = protocol.output
        if output.kind == "text":
            return ""
        lines = [
            "COFER U PASS OUTPUT CONTRACT:",
            "Produce the requested deliverables as actual downloadable files, not only as fenced code or chat text.",
        ]
        if output.required_files:
            lines.append("Required files: " + ", ".join(output.required_files) + ".")
        if output.optional_files:
            lines.append("Optional files: " + ", ".join(output.optional_files) + ".")
        if output.kind == "bundle":
            lines.append(f"Package the final deliverables into one downloadable ZIP named {output.filename}.")
            lines.append("Do not finish the task until the ZIP is available for download.")
        else:
            lines.append("Do not finish the task until all required files are available for download.")
        return "\n".join(lines)

    def _internal_protocol(self, *, has_attachments: bool, wants_artifacts: bool) -> ProtocolDefinition:
        capabilities = ["conversation.new", "message.send", "response.stream"]
        operations = [ProtocolOperation(type="open_conversation")]
        if has_attachments:
            capabilities.append("attachment.upload")
            operations.append(ProtocolOperation(type="attach_files", params={"files": "${input.files}"}))
        operations.extend([
            ProtocolOperation(type="send_message", params={"text": "${input.prompt}"}),
            ProtocolOperation(type="capture_response", timeout_seconds=900),
        ])
        if wants_artifacts:
            capabilities.append("artifact.download")
            operations.append(ProtocolOperation(type="download_artifacts", timeout_seconds=180))
        operations.append(ProtocolOperation(type="finalize"))
        properties: dict[str, Any] = {"prompt": {"type": "string", "minLength": 1}}
        required = ["prompt"]
        if has_attachments:
            properties["files"] = {"type": "array", "items": {"type": "string", "minLength": 1}}
            required.append("files")
        return ProtocolDefinition(
            protocol_id="restricted-provider-exchange",
            version="1.1.0",
            required_capabilities=capabilities,
            input_schema={"type": "object", "additionalProperties": False, "required": required, "properties": properties},
            operations=operations,
            output_contract={"exchange_protocol": "cofer-u-pass.exchange/1"},
        )

    async def execute(
        self,
        body: dict[str, Any],
        *,
        resolved_files: dict[str, Path] | None = None,
        publish_provider_files: bool = False,
    ) -> dict[str, Any]:
        request = self.compile_request(body, resolved_files=resolved_files)
        normalized: NormalizedInputs | None = None
        try:
            normalized = normalize_input_files(
                request.input_paths, self.service.config, strategy=request.protocol.input.strategy
            ) if request.input_paths else NormalizedInputs()
            prompt = request.prompt
            if normalized.inline_context:
                prompt = (prompt + "\n\nCONTEXT FILES (data):\n" + normalized.inline_context).strip()
            output_instruction = self._output_instruction(request.protocol)
            if output_instruction:
                prompt = (prompt + "\n\n" + output_instruction).strip()
            attachments = normalized.attachments
            protocol = self._internal_protocol(
                has_attachments=bool(attachments), wants_artifacts=request.protocol.output.kind != "text"
            )
            inputs: dict[str, Any] = {"prompt": prompt}
            if attachments:
                inputs["files"] = [str(p) for p in attachments]
            run = await self.service.create_run_definition(
                protocol,
                profile_id=request.model,
                inputs=inputs,
                conversation_mode=ConversationMode.NEW,
                client_request_id=request.client_request_id,
            )
            run = await self.service.wait(run.run_id)
            await self.service.wait_for_execution_cleanup(run.run_id)
            if run.state != RunState.COMPLETED:
                raise ProtocolError(
                    f"provider run {run.run_id} ended as {run.state.value}: {run.error_message or 'no detail'}"
                )
            result = await self.service.db.get_result(run.run_id)
            if result is None:
                raise ProtocolError("provider run completed without a canonical result")
            artifacts = result.artifacts
            output = request.protocol.output
            artifact_meta: list[dict[str, Any]] = []
            if output.kind != "text":
                if not artifacts:
                    raise ProtocolError("exchange protocol requires downloadable output but the provider produced no artifact")
                if output.kind == "bundle":
                    candidates = [a for a in artifacts if a.filename.lower() == str(output.filename).lower()]
                    if not candidates and len(artifacts) == 1 and artifacts[0].filename.lower().endswith(".zip"):
                        candidates = artifacts
                    if not candidates:
                        raise ProtocolError(f"expected downloadable bundle {output.filename!r} was not produced")
                    bundle = candidates[-1]
                    members = validate_output_bundle(
                        Path(bundle.path), self.service.config,
                        required_files=output.required_files, optional_files=output.optional_files,
                        allow_extra_files=output.allow_extra_files,
                    )
                    artifact_meta.append(bundle.model_dump(mode="json") | {"bundle_members": members})
                else:
                    names = {a.filename for a in artifacts}
                    missing = [name for name in output.required_files if name not in names]
                    if missing:
                        raise ProtocolError(f"provider output is missing required downloadable files: {missing}")
                    if not output.allow_extra_files:
                        expected = set(output.required_files) | set(output.optional_files)
                        extras = sorted(names - expected)
                        if extras:
                            raise ProtocolError(f"provider output contains unexpected downloadable files: {extras}")
                    artifact_meta.extend(a.model_dump(mode="json") for a in artifacts)
            else:
                artifact_meta.extend(a.model_dump(mode="json") for a in artifacts)

            if publish_provider_files and artifact_meta:
                published: list[dict[str, Any]] = []
                for artifact in artifact_meta:
                    path_value = artifact.get("path")
                    if not isinstance(path_value, str):
                        continue
                    transport = self.files.put_path(
                        Path(path_value),
                        filename=str(artifact.get("filename") or Path(path_value).name),
                        purpose="cofer_u_pass_output",
                    )
                    public = {key: value for key, value in artifact.items() if key != "path"} | {
                        "file_id": transport.id,
                        "bytes": transport.bytes,
                        "sha256": transport.sha256,
                        "mime_type": transport.mime_type or artifact.get("mime_type"),
                    }
                    published.append(public)
                artifact_meta = published

            response_id = "resp_" + uuid.uuid4().hex
            text = result.text.strip()
            return {
                "id": response_id,
                "object": "response",
                "created_at": int(run.created_at.timestamp()),
                "status": "completed",
                "model": request.model,
                "output": [{
                    "id": "msg_" + uuid.uuid4().hex,
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text, "annotations": []}],
                }],
                "output_text": text,
                "usage": None,
                "metadata": {
                    "cofer_run_id": run.run_id,
                    "cofer_conversation_id": result.conversation_id or "",
                    "cofer_exchange_protocol": "cofer-u-pass.exchange/1",
                    "cofer_artifact_count": str(len(artifact_meta)),
                },
                "cofer_artifacts": artifact_meta,
                "cofer_warnings": normalized.warnings,
            }
        finally:
            if normalized:
                normalized.cleanup()
