from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncIterator

from cofer_u_pass.application.service import ApplicationService
from cofer_u_pass.config.settings import AppConfig, load_config
from cofer_u_pass.domain.models import CanonicalResult, ConversationMode, EventEnvelope, RunRecord


class RunHandle:
    def __init__(self, service: ApplicationService, run_id: str):
        self._service = service
        self.run_id = run_id

    async def state(self) -> RunRecord:
        return await self._service.get_run(self.run_id)

    async def events(self, *, after_sequence: int = 0, poll_seconds: float = 0.2) -> AsyncIterator[EventEnvelope]:
        sequence = after_sequence
        terminal = {"completed", "cancelled", "failed", "authentication_required", "recoverable", "outcome_unknown"}
        while True:
            events = await self._service.db.get_events(self.run_id, sequence)
            for event in events:
                sequence = event.sequence
                yield event
            run = await self._service.get_run(self.run_id)
            if run.state.value in terminal and not events:
                break
            await asyncio.sleep(poll_seconds)

    async def wait(self) -> RunRecord:
        return await self._service.wait(self.run_id)

    async def cancel(self) -> RunRecord:
        return await self._service.cancel_run(self.run_id)

    async def resume(self) -> RunRecord:
        return await self._service.resume_run(self.run_id)

    async def result(self) -> CanonicalResult | None:
        return await self._service.db.get_result(self.run_id)

    async def artifacts(self) -> list[dict[str, Any]]:
        return await self._service.db.list_artifacts(self.run_id)


class CoferUPass:
    """Async public façade over the shared application service."""

    def __init__(self, config: AppConfig | None = None):
        self.config = config or load_config()
        self.service = ApplicationService(self.config)
        self._started = False

    async def start(self) -> "CoferUPass":
        if not self._started:
            await self.service.start()
            self._started = True
        return self

    async def close(self) -> None:
        if self._started:
            await self.service.shutdown(cooperative=True)
            self._started = False

    async def __aenter__(self) -> "CoferUPass":
        return await self.start()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def run(
        self,
        protocol: str | Path,
        *,
        profile: str,
        inputs: dict[str, Any],
        conversation_mode: ConversationMode | str = ConversationMode.NEW,
        conversation_id: str | None = None,
        client_request_id: str | None = None,
    ) -> RunHandle:
        await self.start()
        run = await self.service.create_run(
            Path(protocol), profile_id=profile, inputs=inputs,
            conversation_mode=ConversationMode(conversation_mode), conversation_id=conversation_id,
            client_request_id=client_request_id,
        )
        return RunHandle(self.service, run.run_id)

    async def get_run(self, run_id: str) -> RunHandle:
        await self.start()
        await self.service.get_run(run_id)
        return RunHandle(self.service, run_id)
