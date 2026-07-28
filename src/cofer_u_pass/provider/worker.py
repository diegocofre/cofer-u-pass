from __future__ import annotations

import asyncio
import json
import os
import socket
import tempfile
import uuid
from pathlib import Path
from typing import Any

import httpx

from cofer_u_pass.application.service import ApplicationService
from cofer_u_pass.provider.service import RestrictedProviderService


def _file_ids(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for key in ("file_id", "cofer_protocol_file"):
            file_id = value.get(key)
            if isinstance(file_id, str) and file_id.startswith("file-"):
                result.add(file_id)
        for child in value.values():
            result.update(_file_ids(child))
    elif isinstance(value, list):
        for child in value:
            result.update(_file_ids(child))
    return result


class BridgeWorker:
    def __init__(
        self,
        service: ApplicationService,
        *,
        bridge_url: str,
        token: str,
        profiles: list[str],
        worker_id: str | None = None,
    ):
        self.service = service
        self.provider = RestrictedProviderService(service)
        self.bridge_url = bridge_url.rstrip("/")
        self.token = token
        self.profiles = profiles
        self.worker_id = worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self.headers = {"Authorization": f"Bearer {token}"}

    async def _register(self, client: httpx.AsyncClient) -> None:
        profile_payload = []
        for profile_id in self.profiles:
            profile = await self.service.profile_status(profile_id, verify=False)
            caps = await self.provider.model_capabilities(profile_id)
            profile_payload.append({
                "profile_id": profile_id,
                "provider": profile.provider,
                "status": profile.status,
                "capabilities": caps["capabilities"],
            })
        response = await client.post(
            f"{self.bridge_url}/internal/v1/workers/register",
            headers=self.headers,
            json={"worker_id": self.worker_id, "profiles": profile_payload},
        )
        response.raise_for_status()

    async def _download_inputs(self, client: httpx.AsyncClient, body: dict[str, Any], root: Path) -> dict[str, Path]:
        result: dict[str, Path] = {}
        for file_id in sorted(_file_ids(body)):
            async with client.stream(
                "GET",
                f"{self.bridge_url}/internal/v1/files/{file_id}/content",
                headers=self.headers,
            ) as response:
                response.raise_for_status()
                filename = response.headers.get("x-cofer-filename") or file_id
                safe = Path(filename).name or file_id
                path = root / f"{file_id}-{safe}"
                with path.open("wb") as handle:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        handle.write(chunk)
            result[file_id] = path
        return result

    async def _upload_artifacts(self, client: httpx.AsyncClient, job_id: str, response_body: dict[str, Any]) -> list[dict[str, Any]]:
        uploaded: list[dict[str, Any]] = []
        for artifact in response_body.get("cofer_artifacts") or []:
            path_value = artifact.get("path")
            if not isinstance(path_value, str):
                continue
            path = Path(path_value)
            if not path.is_file():
                continue
            async def content_stream():
                with path.open("rb") as handle:
                    while True:
                        chunk = await asyncio.to_thread(handle.read, 1024 * 1024)
                        if not chunk:
                            break
                        yield chunk

            response = await client.post(
                f"{self.bridge_url}/internal/v1/jobs/{job_id}/artifacts",
                params={"filename": artifact.get("filename") or path.name},
                headers={**self.headers, "Content-Type": artifact.get("mime_type") or "application/octet-stream"},
                content=content_stream(),
            )
            response.raise_for_status()
            meta = response.json()
            if artifact.get("bundle_members"):
                meta["bundle_members"] = artifact["bundle_members"]
            uploaded.append(meta)
        return uploaded

    @staticmethod
    def _publish_artifact_refs(response_body: dict[str, Any], uploaded: list[dict[str, Any]]) -> None:
        response_body["cofer_artifacts"] = uploaded
        metadata = response_body.setdefault("metadata", {})
        metadata["cofer_artifact_count"] = str(len(uploaded))
        if not uploaded:
            return
        marker = "\n\n<cofer_artifacts>" + json.dumps({"files": uploaded}, ensure_ascii=False) + "</cofer_artifacts>"
        response_body["output_text"] = (response_body.get("output_text") or "") + marker
        try:
            content = response_body["output"][0]["content"][0]
            content["text"] = (content.get("text") or "") + marker
        except (KeyError, IndexError, TypeError):
            pass

    async def _heartbeat_loop(self, client: httpx.AsyncClient) -> None:
        while True:
            await asyncio.sleep(15)
            response = await client.post(
                f"{self.bridge_url}/internal/v1/workers/{self.worker_id}/heartbeat",
                headers=self.headers,
            )
            response.raise_for_status()

    async def _execute_job(self, client: httpx.AsyncClient, job: dict[str, Any]) -> None:
        job_id = job["job_id"]
        body = dict(job["request"])
        heartbeat = asyncio.create_task(self._heartbeat_loop(client), name=f"cupass-heartbeat:{job_id}")
        try:
            with tempfile.TemporaryDirectory(prefix=f"cupass-worker-{job_id}-", dir=self.service.config.temp_path) as tmp:
                try:
                    resolved = await self._download_inputs(client, body, Path(tmp))
                    response_body = await self.provider.execute(body, resolved_files=resolved)
                    uploaded = await self._upload_artifacts(client, job_id, response_body)
                    self._publish_artifact_refs(response_body, uploaded)
                    response = await client.post(
                        f"{self.bridge_url}/internal/v1/jobs/{job_id}/complete",
                        headers=self.headers,
                        json={"response": response_body},
                    )
                    response.raise_for_status()
                except Exception as exc:
                    try:
                        await client.post(
                            f"{self.bridge_url}/internal/v1/jobs/{job_id}/fail",
                            headers=self.headers,
                            json={"error": f"{type(exc).__name__}: {exc}"},
                        )
                    finally:
                        raise
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except BaseException:
                pass

    async def run(self, *, once: bool = False) -> None:
        timeout = httpx.Timeout(connect=10, read=45, write=120, pool=10)
        async with httpx.AsyncClient(timeout=timeout) as client:
            await self._register(client)
            while True:
                try:
                    response = await client.get(
                        f"{self.bridge_url}/internal/v1/jobs/next",
                        params={"worker_id": self.worker_id, "profiles": ",".join(self.profiles)},
                        headers=self.headers,
                    )
                    if response.status_code == 204:
                        if once:
                            return
                        continue
                    response.raise_for_status()
                    job = response.json()
                    try:
                        await self._execute_job(client, job)
                    except Exception:
                        # _execute_job has already reported the job failure to the bridge.
                        # Keep the worker alive so one provider/protocol failure cannot
                        # take unrelated queued work offline.
                        if once:
                            raise
                        continue
                    if once:
                        return
                except (httpx.HTTPError, OSError):
                    if once:
                        raise
                    await asyncio.sleep(2)


def bridge_token_from_env(name: str = "COFER_U_PASS_BRIDGE_KEY") -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"bridge token environment variable is empty: {name}")
    return value
