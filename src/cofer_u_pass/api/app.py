from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from cofer_u_pass.application.service import ApplicationService
from cofer_u_pass.config.settings import AppConfig, load_config
from cofer_u_pass.domain.models import ConversationMode, RunState


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_path: str
    profile_id: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    conversation_mode: ConversationMode = ConversationMode.NEW
    conversation_id: str | None = None
    client_request_id: str | None = None


class OutcomeResolutionRequest(BaseModel):
    action_id: str
    effect: str


def create_app(config: AppConfig | None = None) -> FastAPI:
    cfg = config or load_config()
    service = ApplicationService(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await service.start()
        app.state.service = service
        try:
            yield
        finally:
            await service.shutdown(cooperative=True)

    app = FastAPI(title="Cofer U Pass", version="1.0.0", lifespan=lifespan)
    app.state.service = service
    if cfg.api.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.api.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "Last-Event-ID"],
        )

    def expected_token() -> str:
        path = cfg.api_token_path
        if not path.exists():
            raise HTTPException(status_code=503, detail="API token missing; run cofer-u-pass setup")
        return path.read_text(encoding="utf-8").strip()

    async def auth(authorization: str | None = Header(default=None)) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")
        import secrets
        supplied = authorization[7:].strip()
        if not secrets.compare_digest(supplied, expected_token()):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")

    @app.get("/api/v1/health")
    async def health(_: None = Depends(auth)):
        ok, detail = await service.db.integrity_check()
        return {"status": "ok" if ok else "degraded", "sqlite": detail}

    @app.post("/api/v1/runs", status_code=202)
    async def create_run(body: CreateRunRequest, _: None = Depends(auth)):
        try:
            run = await service.create_run(
                Path(body.protocol_path), profile_id=body.profile_id, inputs=body.inputs,
                conversation_mode=body.conversation_mode, conversation_id=body.conversation_id,
                client_request_id=body.client_request_id,
            )
            return run.model_dump(mode="json")
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/v1/runs/{run_id}")
    async def get_run(run_id: str, _: None = Depends(auth)):
        try:
            return (await service.get_run(run_id)).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @app.get("/api/v1/runs/{run_id}/status")
    async def get_status(run_id: str, _: None = Depends(auth)):
        try:
            run = await service.get_run(run_id)
            return {"run_id": run_id, "state": run.state.value, "updated_at": run.updated_at}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @app.post("/api/v1/runs/{run_id}/cancel", status_code=202)
    async def cancel(run_id: str, _: None = Depends(auth)):
        try:
            return (await service.cancel_run(run_id)).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @app.post("/api/v1/runs/{run_id}/resume", status_code=202)
    async def resume(run_id: str, _: None = Depends(auth)):
        try:
            return (await service.resume_run(run_id)).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/runs/{run_id}/resolve-outcome", status_code=202)
    async def resolve_outcome(run_id: str, body: OutcomeResolutionRequest, _: None = Depends(auth)):
        try:
            return (await service.resolve_outcome(run_id, body.action_id, effect=body.effect)).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/runs/{run_id}/result")
    async def result(run_id: str, _: None = Depends(auth)):
        try:
            await service.get_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        value = await service.db.get_result(run_id)
        if not value:
            raise HTTPException(status_code=409, detail="result is not available")
        return value.model_dump(mode="json")

    @app.get("/api/v1/runs/{run_id}/artifacts")
    async def artifacts(run_id: str, _: None = Depends(auth)):
        try:
            await service.get_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return {"items": await service.db.list_artifacts(run_id)}

    @app.get("/api/v1/runs/{run_id}/events")
    async def events(run_id: str, request: Request, _: None = Depends(auth), last_event_id: str | None = Header(default=None, alias="Last-Event-ID")):
        try:
            await service.get_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        after = 0
        if last_event_id:
            event = await service.db.get_event_by_id(run_id, last_event_id)
            if event:
                after = event.sequence

        async def stream() -> AsyncIterator[str]:
            nonlocal after
            terminal = {
                RunState.COMPLETED, RunState.CANCELLED, RunState.FAILED,
                RunState.AUTHENTICATION_REQUIRED, RunState.RECOVERABLE, RunState.OUTCOME_UNKNOWN,
            }
            quiet = 0
            while True:
                if await request.is_disconnected():
                    return
                batch = await service.db.get_events(run_id, after)
                if batch:
                    quiet = 0
                    for event in batch:
                        after = event.sequence
                        data = event.model_dump(mode="json")
                        yield f"id: {event.event_id}\nevent: {event.type}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
                else:
                    quiet += 1
                    if quiet % 50 == 0:
                        yield ": keep-alive\n\n"
                run = await service.get_run(run_id)
                if run.state in terminal and not batch:
                    return
                await asyncio.sleep(0.2)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.get("/api/v1/runs/{run_id}/diagnostics")
    async def diagnostics(run_id: str, _: None = Depends(auth)):
        root = cfg.evidence_path / run_id
        items = []
        if root.exists():
            for package in sorted(root.iterdir()):
                if package.is_dir():
                    items.append({"package_id": package.name, "inventory": service.doctor.inventory(package)})
        return {"items": items}

    return app


app = create_app()
