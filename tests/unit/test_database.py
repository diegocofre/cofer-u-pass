from datetime import datetime, timezone

import pytest

from cofer_u_pass.domain.models import (
    ActionPlan, ActionState, ConversationMode, ExecutionPlan, ProfileRecord,
    RetryPolicy, RunRecord, RunState,
)
from cofer_u_pass.persistence.database import Database


def now():
    return datetime.now(timezone.utc)


async def _profile(db, config):
    p = ProfileRecord(profile_id="p", provider="generic", profile_dir=str(config.profiles_path / "p"), created_at=now(), updated_at=now())
    await db.create_profile(p)


def make_run(external=True):
    action = ActionPlan(
        action_id="a1", type="send_message" if external else "capture_response", inputs={},
        preconditions=[], external_effects=["send_message"] if external else [], timeout_seconds=10,
        retry=RetryPolicy(), success_condition="ok", recovery_strategy="reconcile", checkpoint_eligible=True,
    )
    return RunRecord(
        run_id="r", protocol_id="p", protocol_version="1", protocol_hash="h", input_values={}, input_hash="ih",
        profile_id="p", provider="generic", conversation_mode=ConversationMode.NEW, config_hash="ch", config_snapshot={},
        component_versions={}, state=RunState.QUEUED, plan=ExecutionPlan(actions=(action,)), created_at=now(), updated_at=now(),
    )


@pytest.mark.asyncio
async def test_event_order_and_idempotent_run_creation(config):
    db = Database(config.db_path); await db.initialize(); await _profile(db, config)
    run = make_run(); run.client_request_id = "same"
    first = await db.create_run(run)
    duplicate = make_run(); duplicate.run_id = "r2"; duplicate.client_request_id = "same"
    second = await db.create_run(duplicate)
    assert first.run_id == second.run_id == "r"
    await db.append_event("r", "x", {})
    await db.append_event("r", "y", {})
    events = await db.get_events("r")
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))


@pytest.mark.asyncio
async def test_restart_marks_started_external_effect_unknown(config):
    db = Database(config.db_path); await db.initialize(); await _profile(db, config)
    run = make_run(); await db.create_run(run)
    await db.transition_run("r", RunState.RUNNING)
    await db.update_action("r", "a1", ActionState.STARTED, attempt=1)
    await db.recover_interrupted_run("r")
    assert (await db.get_run("r")).state == RunState.OUTCOME_UNKNOWN
