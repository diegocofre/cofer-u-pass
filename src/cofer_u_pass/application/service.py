from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cofer_u_pass.adapters.registry import AdapterRegistry
from cofer_u_pass.browser.locks import ProfileLock, ProfileLockedError
from cofer_u_pass.browser.runtime import BrowserRuntime, playwright_version
from cofer_u_pass.config.settings import AppConfig, ensure_base_layout, restrict_private_path, sanitized_snapshot
from cofer_u_pass.domain.errors import EnvironmentFailure, ProtocolError
from cofer_u_pass.domain.models import (
    ActionState,
    ConversationMode,
    FailureClass,
    ProfileRecord,
    ProtocolDefinition,
    RunRecord,
    RunState,
)
from cofer_u_pass.hooks.runner import HookRunner
from cofer_u_pass.doctor.service import DoctorService
from cofer_u_pass.persistence.artifacts import ArtifactStore
from cofer_u_pass.persistence.database import Database
from cofer_u_pass.protocols.loader import build_plan, load_protocol, sha256_json, validate_inputs
from cofer_u_pass.application.runner import RunExecutor



def _engine_version() -> str:
    try:
        return importlib.metadata.version("cofer-u-pass")
    except importlib.metadata.PackageNotFoundError:
        return "1.0.0"

PROFILE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def _utc() -> datetime:
    return datetime.now(timezone.utc)


class ApplicationService:
    def __init__(self, config: AppConfig, *, doctor_capture=None):
        self.config = config
        ensure_base_layout(config)
        self.db = Database(config.db_path)
        self.registry = AdapterRegistry()
        self.runtime = BrowserRuntime(config)
        self.artifacts = ArtifactStore(config)
        self.hooks = HookRunner(config)
        self.doctor = DoctorService(config, self.db)
        self._global_sem = asyncio.Semaphore(config.browser.global_concurrency)
        self._profile_locks: dict[str, asyncio.Lock] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._accepting = True
        self.executor = RunExecutor(
            config, self.db, self.registry, self.runtime, self.artifacts, self.hooks,
            global_semaphore=self._global_sem, profile_locks=self._profile_locks,
            doctor_capture=doctor_capture or self.doctor.capture_incident,
        )

    async def start(self, *, execute_queued: bool = True) -> None:
        await self.db.initialize()
        # A run is stale only if its authoritative OS profile lock can be acquired.
        # Merely starting another CLI/Doctor process must not disturb a live run.
        for candidate in await self.db.interrupted_run_candidates():
            lock = ProfileLock(Path(candidate["profile_dir"]))
            try:
                await asyncio.to_thread(lock.acquire)
            except ProfileLockedError:
                continue
            else:
                await asyncio.to_thread(lock.release)
                await self.db.recover_interrupted_run(candidate["run_id"])
        if execute_queued:
            for run in await self.db.list_runs({RunState.QUEUED}):
                if run.run_id not in self._tasks:
                    self._spawn(run.run_id, resume=bool(await self.db.latest_checkpoint(run.run_id)))

    async def create_profile(self, profile_id: str, provider: str) -> ProfileRecord:
        if not PROFILE_RE.fullmatch(profile_id):
            raise ValueError("profile name must contain only letters, numbers, dot, underscore, or hyphen")
        if provider not in self.registry.providers():
            raise ValueError(f"unknown provider {provider}; choose from {self.registry.providers()}")
        if await self.db.get_profile(profile_id):
            raise ValueError(f"profile already exists: {profile_id}")
        profile_dir = (self.config.profiles_path / profile_id).resolve()
        if self.config.profiles_path.resolve() not in profile_dir.parents:
            raise ValueError("profile path escape")
        profile_dir.mkdir(parents=True, exist_ok=True)
        restrict_private_path(profile_dir, directory=True)
        now = _utc()
        profile = ProfileRecord(
            profile_id=profile_id, provider=provider, profile_dir=str(profile_dir),
            created_at=now, updated_at=now,
        )
        await self.db.create_profile(profile)
        return profile

    async def authenticate_profile(self, profile_id: str, *, timeout_seconds: float = 900) -> ProfileRecord:
        profile = await self._require_profile(profile_id)
        adapter = self.registry.create(profile.provider)
        lock = ProfileLock(Path(profile.profile_dir))
        try:
            await asyncio.to_thread(lock.acquire)
        except ProfileLockedError as exc:
            raise EnvironmentFailure(f"profile is in use: {profile_id}") from exc
        browser = None
        try:
            browser = await self.runtime.launch_persistent(
                Path(profile.profile_dir), headless=False, allowed_origins=adapter.allowed_origins
            )
            await adapter.navigate_home(browser.page)
            if await adapter.wait_until_authenticated(
                browser.page, timeout_seconds=timeout_seconds, poll_seconds=1.0
            ):
                version = await self.runtime.detect_chromium_version()
                await self.db.update_profile(
                    profile_id, authenticated=True, status="ready", chromium_version=version
                )
                return (await self.db.get_profile(profile_id))  # type: ignore[return-value]
            await self.db.update_profile(profile_id, authenticated=False, status="authentication_required")
            raise TimeoutError(f"authentication was not recognized within {timeout_seconds:g}s")
        finally:
            if browser:
                await browser.close()
            await asyncio.to_thread(lock.release)

    async def profile_status(self, profile_id: str, *, verify: bool = False) -> ProfileRecord:
        profile = await self._require_profile(profile_id)
        if not verify:
            return profile
        adapter = self.registry.create(profile.provider)
        lock = ProfileLock(Path(profile.profile_dir))
        try:
            await asyncio.to_thread(lock.acquire)
        except ProfileLockedError:
            await self.db.update_profile(profile_id, status="busy")
            return (await self.db.get_profile(profile_id))  # type: ignore[return-value]
        browser = None
        try:
            browser = await self.runtime.launch_persistent(
                Path(profile.profile_dir),
                headless=adapter.supports_headless_authentication_check,
                allowed_origins=adapter.allowed_origins,
            )
            await adapter.navigate_home(browser.page)
            verify_timeout = min(15.0, max(3.0, self.config.browser.action_timeout_seconds))
            auth = await adapter.wait_until_authenticated(
                browser.page, timeout_seconds=verify_timeout, poll_seconds=0.5
            )
            await self.db.update_profile(
                profile_id,
                authenticated=auth,
                status="ready" if auth else "authentication_required",
            )
        except Exception:
            await self.db.update_profile(profile_id, status="needs_doctor")
        finally:
            if browser:
                await browser.close()
            await asyncio.to_thread(lock.release)
        return (await self.db.get_profile(profile_id))  # type: ignore[return-value]

    async def list_profiles(self) -> list[ProfileRecord]:
        return await self.db.list_profiles()

    async def import_conversation(self, profile_id: str, url: str) -> str:
        profile = await self._require_profile(profile_id)
        adapter = self.registry.create(profile.provider)
        from cofer_u_pass.browser.runtime import origin
        if origin(url) not in adapter.allowed_origins:
            raise ProtocolError(f"conversation URL origin is not allowed for {profile.provider}")
        lock = ProfileLock(Path(profile.profile_dir))
        await asyncio.to_thread(lock.acquire)
        browser = None
        try:
            browser = await self.runtime.launch_persistent(Path(profile.profile_dir), headless=False, allowed_origins=adapter.allowed_origins)
            await browser.page.goto(url, wait_until="domcontentloaded")
            await adapter.ensure_authenticated(browser.page)
            external_id = adapter.extract_conversation_id(browser.page.url)
            if not external_id:
                raise ProtocolError("adapter could not recognize a conversation identifier in this URL")
            conversation_id = str(uuid.uuid4())
            await self.db.register_conversation(
                conversation_id, profile_id, profile.provider, external_id=external_id, url=browser.page.url, imported=True
            )
            return conversation_id
        finally:
            if browser:
                await browser.close()
            await asyncio.to_thread(lock.release)

    async def create_run(
        self,
        protocol_path: Path,
        *,
        profile_id: str,
        inputs: dict[str, Any],
        conversation_mode: ConversationMode = ConversationMode.NEW,
        conversation_id: str | None = None,
        client_request_id: str | None = None,
        spawn: bool = True,
    ) -> RunRecord:
        protocol = load_protocol(protocol_path)
        return await self.create_run_definition(
            protocol, profile_id=profile_id, inputs=inputs, conversation_mode=conversation_mode,
            conversation_id=conversation_id, client_request_id=client_request_id, spawn=spawn,
        )

    async def create_run_definition(
        self,
        protocol: ProtocolDefinition,
        *,
        profile_id: str,
        inputs: dict[str, Any],
        conversation_mode: ConversationMode = ConversationMode.NEW,
        conversation_id: str | None = None,
        client_request_id: str | None = None,
        spawn: bool = True,
    ) -> RunRecord:
        if not self._accepting:
            raise EnvironmentFailure("service is shutting down and is not accepting new runs")
        profile = await self._require_profile(profile_id)
        validated_inputs = validate_inputs(protocol, inputs)
        adapter = self.registry.create(profile.provider)
        missing = set(protocol.required_capabilities) - adapter.capabilities
        if missing:
            raise ProtocolError(f"protocol requires unsupported capabilities: {sorted(missing)}")
        if conversation_mode != ConversationMode.NEW and not conversation_id:
            raise ProtocolError("continue/imported conversation modes require conversation_id")
        if conversation_id:
            conversation = await self.db.get_conversation(conversation_id)
            if not conversation or conversation["profile_id"] != profile_id:
                raise ProtocolError("conversation does not belong to selected profile")
        plan = build_plan(protocol, validated_inputs, self.config.browser.action_timeout_seconds)
        hook_versions: dict[str, str] = {}
        for action in plan.actions:
            if action.type != "hook":
                continue
            hook_id = action.inputs.get("id")
            hook_version = action.inputs.get("version")
            hook_ref = action.inputs.get("ref")
            if not all(isinstance(v, str) and v.strip() for v in (hook_id, hook_version, hook_ref)):
                raise ProtocolError("hook operations require versioned params.id, params.version, and params.ref")
            key = f"hook:{hook_id}"
            if key in hook_versions and hook_versions[key] != hook_version:
                raise ProtocolError(f"hook {hook_id} is referenced with conflicting versions")
            hook_versions[key] = hook_version
        snapshot = sanitized_snapshot(self.config)
        component_versions = {
            "engine": _engine_version(),
            "contract": "1.0",
            "protocol_schema": "1.0",
            "event_schema": "1.0",
            "block_schema": "1.0",
            "adapter": adapter.adapter_version,
            "rules": adapter.rules.version,
            "rule_schema": adapter.rules.schema_version,
            "playwright": playwright_version(),
            "chromium": profile.chromium_version or "unknown",
            **hook_versions,
        }
        now = _utc()
        run = RunRecord(
            run_id=str(uuid.uuid4()), protocol_id=protocol.protocol_id, protocol_version=protocol.version,
            protocol_hash=sha256_json(protocol.model_dump(mode="json")), input_values=validated_inputs,
            input_hash=sha256_json(validated_inputs), profile_id=profile_id, provider=profile.provider,
            conversation_mode=conversation_mode, conversation_id=conversation_id, client_request_id=client_request_id,
            config_hash=sha256_json(snapshot), config_snapshot=snapshot, component_versions=component_versions,
            state=RunState.QUEUED, plan=plan, created_at=now, updated_at=now,
        )
        stored = await self.db.create_run(run)
        if spawn and stored.run_id not in self._tasks and stored.state == RunState.QUEUED:
            self._spawn(stored.run_id, resume=False)
        return stored

    def _spawn(self, run_id: str, *, resume: bool) -> None:
        async def task_body():
            try:
                await self.executor.execute(run_id, resume=resume)
            finally:
                self._tasks.pop(run_id, None)
        self._tasks[run_id] = asyncio.create_task(task_body(), name=f"cofer-u-pass:{run_id}")

    async def get_run(self, run_id: str) -> RunRecord:
        run = await self.db.get_run(run_id)
        if not run:
            raise KeyError(run_id)
        return run

    async def cancel_run(self, run_id: str) -> RunRecord:
        run = await self.get_run(run_id)
        if run.state in {RunState.COMPLETED, RunState.CANCELLED, RunState.FAILED}:
            return run
        if run.state in {RunState.AUTHENTICATION_REQUIRED, RunState.RECOVERABLE, RunState.OUTCOME_UNKNOWN}:
            await self.db.transition_run(run_id, RunState.CANCELLING, event_type="run.cancelling")
            await self.db.transition_run(run_id, RunState.CANCELLED, event_type="run.cancelled")
        elif run.state != RunState.CANCELLING:
            await self.db.transition_run(run_id, RunState.CANCELLING, event_type="run.cancelling")
        return await self.get_run(run_id)

    async def resume_run(self, run_id: str) -> RunRecord:
        run = await self.get_run(run_id)
        if run.state not in {RunState.RECOVERABLE, RunState.AUTHENTICATION_REQUIRED}:
            raise ValueError("only recoverable or authentication_required runs can be resumed directly")
        if run.state == RunState.AUTHENTICATION_REQUIRED:
            profile = await self.profile_status(run.profile_id, verify=False)
            if not profile.authenticated:
                raise ValueError("reauthenticate the profile before resuming")
        await self.db.transition_run(run_id, RunState.QUEUED, event_type="run.resume_requested")
        self._spawn(run_id, resume=True)
        return await self.get_run(run_id)

    async def resolve_outcome(self, run_id: str, action_id: str, *, effect: str) -> RunRecord:
        run = await self.get_run(run_id)
        if run.state != RunState.OUTCOME_UNKNOWN:
            raise ValueError("run is not outcome_unknown")
        actions = await self.db.get_actions(run_id)
        row = next((a for a in actions if a["action_id"] == action_id), None)
        if not row or row["state"] != ActionState.OUTCOME_UNKNOWN.value:
            raise ValueError("action is not outcome_unknown")
        if effect == "occurred":
            await self.db.update_action(
                run_id, action_id, ActionState.CONFIRMED, evidence={"manual_resolution": "effect_occurred"},
                event_type="action.manually_resolved",
            )
        elif effect == "not-occurred":
            await self.db.update_action(
                run_id, action_id, ActionState.PLANNED, evidence={"manual_resolution": "effect_not_occurred"},
                event_type="action.manually_resolved",
            )
        else:
            raise ValueError("effect must be 'occurred' or 'not-occurred'")
        await self.db.transition_run(run_id, RunState.QUEUED, event_type="run.manual_resolution")
        self._spawn(run_id, resume=True)
        return await self.get_run(run_id)

    async def wait(self, run_id: str, *, poll_seconds: float = 0.2) -> RunRecord:
        terminal = {
            RunState.COMPLETED, RunState.CANCELLED, RunState.FAILED,
            RunState.AUTHENTICATION_REQUIRED, RunState.RECOVERABLE, RunState.OUTCOME_UNKNOWN,
        }
        while True:
            run = await self.get_run(run_id)
            if run.state in terminal:
                return run
            await asyncio.sleep(poll_seconds)

    async def wait_for_execution_cleanup(self, run_id: str) -> None:
        """Wait until the in-process executor task has released runtime resources.

        Public run state can become terminal before the executor's ``finally``
        block finishes closing Playwright and releasing the profile lease/lock.
        CLI callers use this barrier before letting ``asyncio.run`` tear down the
        event loop.
        """
        task = self._tasks.get(run_id)
        if task is not None:
            await asyncio.shield(task)

    async def shutdown(self, *, cooperative: bool = True) -> None:
        self._accepting = False
        if cooperative:
            # Preserve queued runs exactly as queued. Active runs are cooperatively cancelled
            # at their next safe action boundary.
            for run in await self.db.list_runs({RunState.RUNNING}):
                try:
                    await self.cancel_run(run.run_id)
                except Exception:
                    pass
            for run_id, task in list(self._tasks.items()):
                current = await self.db.get_run(run_id)
                if current and current.state == RunState.QUEUED:
                    task.cancel()
            if self._tasks:
                await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)
        else:
            for task in self._tasks.values():
                task.cancel()

    async def cleanup(self, *, apply: bool = False) -> dict[str, Any]:
        """Conservative explicit retention cleanup. Profiles and conversations are never removed."""
        from datetime import timedelta
        import shutil

        if await self.db.has_active_runs():
            raise RuntimeError("cleanup requires no queued/running/cancelling runs")
        now = _utc()
        event_cutoff = now - timedelta(days=self.config.retention.events_days)
        run_cutoff = now - timedelta(days=max(self.config.retention.completed_runs_days, self.config.retention.artifacts_days))
        evidence_cutoff = now - timedelta(days=self.config.retention.evidence_days)
        backup_cutoff = now - timedelta(days=self.config.retention.backups_days)

        all_runs = await self.db.list_runs()
        safe_terminal = {RunState.COMPLETED, RunState.CANCELLED, RunState.FAILED}
        state_by_id = {r.run_id: r.state for r in all_runs}
        run_candidates = [r for r in all_runs if r.state in safe_terminal and r.updated_at < run_cutoff]
        event_count = await self.db.count_events_before(event_cutoff.isoformat())

        evidence_candidates: list[Path] = []
        if self.config.evidence_path.exists():
            for run_dir in self.config.evidence_path.iterdir():
                if not run_dir.is_dir():
                    continue
                state = state_by_id.get(run_dir.name)
                if state and state not in safe_terminal:
                    continue
                for package in run_dir.iterdir():
                    if package.is_dir():
                        mtime = datetime.fromtimestamp(package.stat().st_mtime, timezone.utc)
                        if mtime < evidence_cutoff:
                            evidence_candidates.append(package)

        backups = sorted(
            [p for p in self.config.backups_path.glob("*.sqlite3") if p.is_file()],
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        protected = set(backups[:3])
        backup_candidates = [
            p for p in backups[3:]
            if datetime.fromtimestamp(p.stat().st_mtime, timezone.utc) < backup_cutoff
        ]

        log_candidates = []
        if self.config.logs_path.exists():
            for p in self.config.logs_path.iterdir():
                if p.is_file() and datetime.fromtimestamp(p.stat().st_mtime, timezone.utc) < event_cutoff:
                    log_candidates.append(p)

        artifact_paths: list[Path] = []
        for run in run_candidates:
            for item in await self.db.list_artifacts(run.run_id):
                p = Path(item["path"]).resolve()
                root = self.config.artifacts_path.resolve()
                if root in p.parents and p.exists():
                    artifact_paths.append(p)

        plan = {
            "apply": apply,
            "events": event_count,
            "runs": [r.run_id for r in run_candidates],
            "artifacts": [str(p) for p in artifact_paths],
            "evidence": [str(p) for p in evidence_candidates],
            "backups": [str(p) for p in backup_candidates],
            "logs": [str(p) for p in log_candidates],
            "protected_recent_backups": [str(p) for p in backups[:3]],
        }
        if not apply:
            return plan

        await self.db.delete_events_before(event_cutoff.isoformat())
        for p in artifact_paths:
            p.unlink(missing_ok=True)
        for run in run_candidates:
            await self.db.delete_run(run.run_id)
            shutil.rmtree(self.config.temp_path / run.run_id, ignore_errors=True)
            run_artifacts = self.config.artifacts_path / run.run_id
            if run_artifacts.exists():
                shutil.rmtree(run_artifacts, ignore_errors=True)
        for package in evidence_candidates:
            shutil.rmtree(package, ignore_errors=True)
            parent = package.parent
            try:
                if parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError:
                pass
        for p in backup_candidates + log_candidates:
            p.unlink(missing_ok=True)
        return plan

    async def _require_profile(self, profile_id: str) -> ProfileRecord:
        profile = await self.db.get_profile(profile_id)
        if not profile:
            raise KeyError(f"profile not found: {profile_id}")
        return profile
