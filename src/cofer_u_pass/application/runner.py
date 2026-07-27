from __future__ import annotations

import asyncio
import importlib.metadata
import os
import shutil
import stat
import time
import uuid
from pathlib import Path
from typing import Any

from cofer_u_pass.adapters.registry import AdapterRegistry
from cofer_u_pass.browser.locks import ProfileLock, ProfileLockedError
from cofer_u_pass.browser.runtime import BrowserRuntime, playwright_version
from cofer_u_pass.config.settings import AppConfig
from cofer_u_pass.domain.blocks import block_to_markdown, block_to_text
from cofer_u_pass.domain.errors import (
    AdapterActionError,
    AdapterMismatch,
    AuthenticationRequired,
    CoferUPassError,
    EnvironmentFailure,
    OutcomeUnknown,
    ProtocolError,
    TransientFailure,
)
from cofer_u_pass.domain.models import (
    ActionPlan,
    ActionState,
    ArtifactRef,
    Block,
    CanonicalResult,
    Checkpoint,
    ConversationMode,
    FailureClass,
    RunState,
)
from cofer_u_pass.hooks.runner import HookRunner
from cofer_u_pass.persistence.artifacts import ArtifactStore
from cofer_u_pass.persistence.database import Database


class RunExecutor:
    def __init__(
        self,
        config: AppConfig,
        db: Database,
        registry: AdapterRegistry,
        runtime: BrowserRuntime,
        artifacts: ArtifactStore,
        hooks: HookRunner,
        *,
        global_semaphore: asyncio.Semaphore,
        profile_locks: dict[str, asyncio.Lock],
        doctor_capture=None,
    ):
        self.config = config
        self.db = db
        self.registry = registry
        self.runtime = runtime
        self.artifacts = artifacts
        self.hooks = hooks
        self.global_semaphore = global_semaphore
        self.profile_locks = profile_locks
        self.doctor_capture = doctor_capture

    async def _wait_os_lock(self, lock: ProfileLock, run_id: str) -> None:
        emitted = False
        while True:
            run = await self.db.get_run(run_id)
            if run and run.state == RunState.CANCELLING:
                raise asyncio.CancelledError
            try:
                await asyncio.to_thread(lock.acquire)
                return
            except ProfileLockedError:
                if not emitted:
                    await self.db.append_event(run_id, "queue.profile_busy", {})
                    emitted = True
                await asyncio.sleep(0.5)

    async def _heartbeat(self, profile_id: str, run_id: str) -> None:
        while True:
            await asyncio.sleep(5)
            await self.db.heartbeat_lease(profile_id, run_id)

    def _current_engine_version(self) -> str:
        try:
            return importlib.metadata.version("cofer-u-pass")
        except importlib.metadata.PackageNotFoundError:
            return "1.0.0"

    def _verify_component_versions(self, run, adapter, *, resume: bool) -> None:
        current = {
            "engine": self._current_engine_version(),
            "contract": "1.0",
            "protocol_schema": "1.0",
            "event_schema": "1.0",
            "block_schema": "1.0",
            "adapter": adapter.adapter_version,
            "rules": adapter.rules.version,
            "rule_schema": adapter.rules.schema_version,
            "playwright": playwright_version(),
        }
        mismatches = {
            key: (run.component_versions.get(key), value)
            for key, value in current.items()
            if run.component_versions.get(key) not in {None, value}
        }
        if mismatches:
            detail = ", ".join(f"{k}: run={a} current={b}" for k, (a, b) in mismatches.items())
            raise EnvironmentFailure(
                ("resume component identity mismatch" if resume else "run component identity mismatch") + f": {detail}"
            )

    async def _verify_checkpoint_artifacts(self, run_id: str, checkpoint: Checkpoint) -> None:
        if not checkpoint.artifact_ids:
            return
        import hashlib
        items = {item["artifact_id"]: item for item in await self.db.list_artifacts(run_id)}
        for artifact_id in checkpoint.artifact_ids:
            item = items.get(artifact_id)
            if not item:
                raise OutcomeUnknown(f"checkpoint artifact metadata is missing: {artifact_id}")
            path = Path(item["path"]).resolve()
            root = self.config.artifacts_path.resolve()
            if root not in path.parents or not path.is_file():
                raise OutcomeUnknown(f"checkpoint artifact file is missing or unsafe: {artifact_id}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != item["sha256"]:
                raise OutcomeUnknown(f"checkpoint artifact hash mismatch: {artifact_id}")

    async def _preflight_files(self, run, adapter) -> None:
        profile = await self.db.get_profile(run.profile_id)
        if not profile:
            raise EnvironmentFailure("profile metadata is missing")
        profile_path = Path(profile.profile_dir)
        expected_root = self.config.profiles_path.resolve()
        if profile_path.is_symlink():
            raise EnvironmentFailure("profile directory must not be a symlink")
        try:
            resolved_profile = profile_path.resolve(strict=True)
        except FileNotFoundError as exc:
            raise EnvironmentFailure("profile directory does not exist") from exc
        if expected_root not in resolved_profile.parents:
            raise EnvironmentFailure("profile directory is outside the configured profiles root")
        if not os.access(resolved_profile, os.R_OK | os.W_OK | os.X_OK):
            raise EnvironmentFailure("profile directory is not readable/writable by the current user")
        if os.name != "nt":
            mode = stat.S_IMODE(resolved_profile.stat().st_mode)
            if mode & 0o077:
                raise EnvironmentFailure(f"profile directory permissions are too broad: {oct(mode)}; expected 0700")
        missing = set(run.plan.required_capabilities) - adapter.capabilities
        if missing:
            raise ProtocolError(f"adapter {adapter.provider} lacks capabilities: {sorted(missing)}")
        ok, detail = await self.db.integrity_check()
        if not ok:
            raise EnvironmentFailure(f"SQLite integrity check failed: {detail}")
        usage = shutil.disk_usage(self.config.data_path)
        if usage.free < 128 * 1024 * 1024:
            raise EnvironmentFailure("less than 128 MiB free in data root")
        for action in run.plan.actions:
            if action.type == "attach_files":
                for raw in action.inputs.get("files", []):
                    self.artifacts.validate_input(Path(raw))

    async def execute(self, run_id: str, *, resume: bool = False) -> None:
        run = await self.db.get_run(run_id)
        if not run:
            return
        profile = await self.db.get_profile(run.profile_id)
        if not profile:
            await self._fail(run_id, EnvironmentFailure("profile not found"), page=None)
            return
        adapter = self.registry.create(run.provider)
        local_lock = self.profile_locks.setdefault(run.profile_id, asyncio.Lock())
        async with local_lock:
            async with self.global_semaphore:
                os_lock = ProfileLock(Path(profile.profile_dir))
                browser = None
                heartbeat = None
                try:
                    await self.db.append_event(run_id, "queue.acquiring_profile", {"profile_id": run.profile_id})
                    await self._wait_os_lock(os_lock, run_id)
                    await self.db.acquire_lease(run.profile_id, run_id, os.getpid())
                    heartbeat = asyncio.create_task(self._heartbeat(run.profile_id, run_id))
                    current = await self.db.get_run(run_id)
                    if not current or current.state == RunState.CANCELLING:
                        raise asyncio.CancelledError
                    await self.db.transition_run(run_id, RunState.RUNNING, event_type="run.started")
                    run = await self.db.get_run(run_id)
                    assert run
                    self._verify_component_versions(run, adapter, resume=resume)
                    await self._preflight_files(run, adapter)
                    chromium_version = await self.runtime.detect_chromium_version()
                    if profile.chromium_version and profile.chromium_version != chromium_version:
                        raise EnvironmentFailure(
                            f"profile Chromium version {profile.chromium_version} does not match managed runtime {chromium_version}; "
                            "reauthenticate/validate the profile before continuing"
                        )
                    if not profile.chromium_version:
                        await self.db.update_profile(run.profile_id, chromium_version=chromium_version)
                    await self.db.update_run_component_versions(run_id, {"chromium": chromium_version})
                    run = await self.db.get_run(run_id)
                    assert run
                    headless = bool(run.config_snapshot.get("browser", {}).get("headless_default", False))
                    if headless and not adapter.supports_headless_execution:
                        raise ProtocolError(
                            f"adapter {adapter.provider} does not declare reliable headless execution support"
                        )
                    browser = await self.runtime.launch_persistent(
                        Path(profile.profile_dir), headless=headless, allowed_origins=adapter.allowed_origins
                    )
                    await adapter.navigate_home(browser.page)
                    auth_timeout = min(15.0, max(3.0, self.config.browser.action_timeout_seconds))
                    await adapter.ensure_authenticated(
                        browser.page, timeout_seconds=auth_timeout, poll_seconds=0.5
                    )
                    await self.db.append_event(run_id, "preflight.completed", {"provider": run.provider, "headless": headless})

                    actions = await self.db.get_actions(run_id)
                    checkpoint = await self.db.latest_checkpoint(run_id)
                    if resume and checkpoint:
                        await self._verify_checkpoint_artifacts(run_id, checkpoint)
                        ok = await adapter.reconcile(browser.page, checkpoint.model_dump(mode="json"))
                        if not ok:
                            raise OutcomeUnknown("checkpoint reconciliation could not establish a safe continuation")
                        await self.db.append_event(run_id, "reconciliation.completed", {"checkpoint_id": checkpoint.checkpoint_id})

                    persisted_artifacts = [ArtifactRef.model_validate(item) for item in await self.db.list_artifacts(run_id)]
                    persisted_hook_results = [
                        row.get("evidence", {}).get("result")
                        for row in actions
                        if row.get("type") == "hook" and row.get("state") == ActionState.CONFIRMED.value
                        and isinstance(row.get("evidence", {}).get("result"), dict)
                    ]
                    state: dict[str, Any] = {
                        "block": checkpoint.blocks if checkpoint else None,
                        "artifacts": persisted_artifacts,
                        "hook_results": persisted_hook_results,
                        "conversation_id": run.conversation_id,
                        "last_confirmed": None,
                    }
                    for ordinal, row in enumerate(actions):
                        action = ActionPlan.model_validate(row["plan"])
                        if row["state"] == ActionState.CONFIRMED.value:
                            state["last_confirmed"] = {"action_type": action.type, "evidence": row.get("evidence", {})}
                            continue
                        if action.type != "open_conversation":
                            await adapter.ensure_authenticated(browser.page)
                        latest = await self.db.get_run(run_id)
                        if latest and latest.state == RunState.CANCELLING:
                            await self.db.transition_run(run_id, RunState.CANCELLED, event_type="run.cancelled")
                            return
                        await self._execute_action(run, browser.page, adapter, action, ordinal, state)

                    latest = await self.db.get_run(run_id)
                    if latest and latest.state == RunState.RUNNING:
                        await self.db.transition_run(run_id, RunState.COMPLETED, event_type="run.completed")
                except asyncio.CancelledError:
                    current = await self.db.get_run(run_id)
                    if current and current.state == RunState.CANCELLING:
                        await self.db.transition_run(run_id, RunState.CANCELLED, event_type="run.cancelled")
                except AuthenticationRequired as exc:
                    await self.db.transition_run(
                        run_id, RunState.AUTHENTICATION_REQUIRED, event_type="run.authentication_required",
                        error_class=FailureClass.AUTHENTICATION, error_message=str(exc),
                    )
                except OutcomeUnknown as exc:
                    await self._fail(run_id, exc, page=browser.page if browser else None)
                except Exception as exc:
                    await self._fail(run_id, exc, page=browser.page if browser else None)
                finally:
                    if heartbeat:
                        heartbeat.cancel()
                        try:
                            await heartbeat
                        except BaseException:
                            pass
                    if browser:
                        try:
                            await browser.close()
                        except Exception:
                            pass
                    await self.db.release_lease(run.profile_id, run_id)
                    await asyncio.to_thread(os_lock.release)

    async def _execute_action(self, run, page, adapter, action: ActionPlan, ordinal: int, state: dict[str, Any]) -> None:
        max_attempts = action.retry.max_attempts
        for attempt in range(1, max_attempts + 1):
            await self.db.update_action(run.run_id, action.action_id, ActionState.STARTED, attempt=attempt, event_type="action.started")
            effect_possible = False
            try:
                evidence = await asyncio.wait_for(
                    self._perform_action(run, page, adapter, action, ordinal, state),
                    timeout=action.timeout_seconds,
                )
                next_id = run.plan.actions[ordinal + 1].action_id if ordinal + 1 < len(run.plan.actions) else None
                checkpoint = None
                if action.checkpoint_eligible:
                    checkpoint = Checkpoint(
                        checkpoint_id=str(uuid.uuid4()), run_id=run.run_id, action_id=action.action_id,
                        conversation_id=state.get("conversation_id"), current_url=page.url,
                        logical_state={"provider": run.provider, "action_type": action.type},
                        component_versions=run.component_versions, protocol_hash=run.protocol_hash,
                        input_hash=run.input_hash, artifact_ids=[a.artifact_id for a in state.get("artifacts", [])],
                        blocks=state.get("block"), next_action_id=next_id, evidence=evidence,
                    )
                await self.db.confirm_action_with_checkpoint(run.run_id, action.action_id, checkpoint, evidence)
                state["last_confirmed"] = {"action_type": action.type, "evidence": evidence}
                return
            except AdapterActionError as exc:
                effect_possible = exc.external_effect_possible
                failure_class = exc.failure_class
                if effect_possible and action.external_effects:
                    await self.db.update_action(
                        run.run_id, action.action_id, ActionState.OUTCOME_UNKNOWN,
                        attempt=attempt, error_class=FailureClass.OUTCOME_UNKNOWN, error_message=str(exc), evidence={},
                    )
                    raise OutcomeUnknown(str(exc)) from exc
                if failure_class == FailureClass.TRANSIENT and attempt < max_attempts:
                    await self.db.update_action(
                        run.run_id, action.action_id, ActionState.RETRYABLE_FAILED,
                        attempt=attempt, error_class=failure_class, error_message=str(exc), evidence={}, event_type="action.retrying",
                    )
                    await asyncio.sleep(action.retry.base_delay_seconds * (2 ** (attempt - 1)))
                    continue
                await self.db.update_action(
                    run.run_id, action.action_id, ActionState.FAILED,
                    attempt=attempt, error_class=failure_class, error_message=str(exc), evidence={},
                )
                raise
            except TransientFailure as exc:
                if action.external_effects:
                    # The adapter did not explicitly prove the external effect was absent.
                    await self.db.update_action(
                        run.run_id, action.action_id, ActionState.OUTCOME_UNKNOWN,
                        attempt=attempt, error_class=FailureClass.OUTCOME_UNKNOWN, error_message=str(exc), evidence={},
                    )
                    raise OutcomeUnknown(str(exc)) from exc
                if attempt < max_attempts:
                    await self.db.update_action(
                        run.run_id, action.action_id, ActionState.RETRYABLE_FAILED,
                        attempt=attempt, error_class=FailureClass.TRANSIENT, error_message=str(exc), evidence={}, event_type="action.retrying",
                    )
                    await asyncio.sleep(action.retry.base_delay_seconds * (2 ** (attempt - 1)))
                    continue
                raise
            except asyncio.TimeoutError as exc:
                if action.external_effects:
                    raise OutcomeUnknown(f"action timed out after a possible external effect: {action.action_id}") from exc
                if attempt < max_attempts:
                    await self.db.update_action(
                        run.run_id, action.action_id, ActionState.RETRYABLE_FAILED,
                        attempt=attempt, error_class=FailureClass.TRANSIENT, error_message="action timeout", evidence={}, event_type="action.retrying",
                    )
                    continue
                raise TransientFailure(f"action timed out: {action.action_id}") from exc
            except Exception as exc:
                failure = exc.failure_class if isinstance(exc, CoferUPassError) else FailureClass.FATAL
                proven_pre_effect = isinstance(exc, (ProtocolError, AuthenticationRequired, AdapterMismatch))
                if action.external_effects and not proven_pre_effect:
                    await self.db.update_action(
                        run.run_id, action.action_id, ActionState.OUTCOME_UNKNOWN,
                        attempt=attempt, error_class=FailureClass.OUTCOME_UNKNOWN, error_message=str(exc), evidence={},
                    )
                    raise OutcomeUnknown(
                        f"{action.action_id} failed after an external effect may have occurred: {exc}"
                    ) from exc
                await self.db.update_action(
                    run.run_id, action.action_id, ActionState.FAILED,
                    attempt=attempt, error_class=failure, error_message=str(exc), evidence={},
                )
                raise

    async def _perform_action(self, run, page, adapter, action: ActionPlan, ordinal: int, state: dict[str, Any]) -> dict[str, Any]:
        if action.type == "open_conversation":
            conversation = None
            mode = run.conversation_mode.value
            if run.conversation_id:
                conversation = await self.db.get_conversation(run.conversation_id)
            evidence = await adapter.open_conversation(page, mode, conversation)
            if not state.get("conversation_id"):
                state["conversation_id"] = str(uuid.uuid4())
                await self.db.set_run_conversation(run.run_id, state["conversation_id"])
            await self.db.register_conversation(
                state["conversation_id"], run.profile_id, run.provider,
                external_id=evidence.data.get("conversation_external_id"), url=evidence.data.get("url"), imported=False,
            )
            return evidence.data

        if action.type == "attach_files":
            paths = [self.artifacts.validate_input(Path(p)) for p in action.inputs.get("files", [])]
            return (await adapter.attach_files(page, paths)).data

        if action.type == "send_message":
            text = action.inputs.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ProtocolError("send_message requires non-empty params.text")
            evidence = await adapter.send_message(page, text)
            external = adapter.extract_conversation_id(page.url)
            if state.get("conversation_id"):
                await self.db.register_conversation(
                    state["conversation_id"], run.profile_id, run.provider, external_id=external, url=page.url, imported=False,
                )
            return evidence.data | {"url": page.url, "conversation_external_id": external}

        if action.type == "capture_response":
            async def emit(kind: str, payload: dict[str, Any]) -> None:
                await self.db.append_event(run.run_id, kind, payload)
            block, evidence = await adapter.capture_response(
                page,
                timeout_seconds=action.timeout_seconds,
                stability_seconds=self.config.browser.response_stability_seconds,
                emit=emit,
            )
            state["block"] = block
            return evidence

        if action.type == "download_artifacts":
            tmp = self.config.temp_path / run.run_id / action.action_id
            downloaded = await adapter.download_artifacts(page, tmp)
            refs = []
            for path, source in downloaded:
                ref = self.artifacts.ingest(path, run_id=run.run_id, action_id=action.action_id, original_source=source)
                await self.db.store_artifact(ref)
                state["artifacts"].append(ref)
                refs.append(ref.model_dump(mode="json"))
                await self.db.append_event(run.run_id, "artifact.created", ref.model_dump(mode="json"))
            return {"artifacts": refs}

        if action.type == "hook":
            ref = action.inputs.get("ref")
            if not isinstance(ref, str):
                raise ProtocolError("hook requires params.ref=module:function")
            payload = action.inputs.get("input", {})
            result = await self.hooks.run(
                ref=ref, payload=payload, run_dir=self.config.temp_path / run.run_id / action.action_id,
                input_schema=action.inputs.get("input_schema"), output_schema=action.inputs.get("output_schema"),
                timeout=action.timeout_seconds,
            )
            state["hook_results"].append(result["result"])
            return {"hook": ref, "result": result["result"], "exit_code": result["exit_code"]}

        if action.type == "checkpoint":
            return {"explicit": True, "url": page.url, "prior": state.get("last_confirmed")}

        if action.type == "finalize":
            block = state.get("block") or Block(type="document", children=[])
            artifacts = state.get("artifacts", [])
            result = CanonicalResult(
                run_id=run.run_id, blocks=block, markdown=block_to_markdown(block), text=block_to_text(block),
                artifacts=artifacts, provider=run.provider, profile_id=run.profile_id,
                conversation_id=state.get("conversation_id"), metadata={"hook_results": state.get("hook_results", [])},
            )
            await self.db.store_result(result)
            await self.db.append_event(run.run_id, "result.available", {"run_id": run.run_id})
            return {"result_hash": __import__("hashlib").sha256(result.model_dump_json().encode()).hexdigest()}

        raise ProtocolError(f"unsupported action type: {action.type}")

    async def _fail(self, run_id: str, exc: Exception, page=None) -> None:
        if isinstance(exc, AuthenticationRequired):
            failure = FailureClass.AUTHENTICATION
        elif isinstance(exc, OutcomeUnknown):
            failure = FailureClass.OUTCOME_UNKNOWN
        elif isinstance(exc, CoferUPassError):
            failure = exc.failure_class
        else:
            failure = FailureClass.FATAL
        if failure == FailureClass.OUTCOME_UNKNOWN:
            target = RunState.OUTCOME_UNKNOWN
        elif failure == FailureClass.ENVIRONMENT:
            target = RunState.RECOVERABLE
        else:
            target = RunState.FAILED
        current = await self.db.get_run(run_id)
        if not current or current.state in {RunState.COMPLETED, RunState.CANCELLED, RunState.FAILED}:
            return
        try:
            await self.db.transition_run(
                run_id, target, event_type="run.failed" if target == RunState.FAILED else f"run.{target.value}",
                error_class=failure, error_message=str(exc),
            )
        except ValueError:
            pass
        if self.doctor_capture and failure in {FailureClass.ADAPTER_MISMATCH, FailureClass.FATAL, FailureClass.ENVIRONMENT}:
            try:
                await self.doctor_capture(run_id, failure.value, str(exc), page=page)
            except Exception:
                pass
