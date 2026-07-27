from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from cofer_u_pass.application.service import ApplicationService
from cofer_u_pass.domain.models import (
    ActionPlan, ConversationMode, ExecutionPlan, ProfileRecord, RetryPolicy, RunRecord, RunState,
)


@pytest.mark.asyncio
async def test_cleanup_removes_only_old_resolved_run_and_preserves_profile(config):
    service = ApplicationService(config)
    await service.start()
    now = datetime.now(timezone.utc)
    profile = ProfileRecord(
        profile_id="keep-profile", provider="generic", profile_dir=str(config.profiles_path / "keep-profile"),
        created_at=now, updated_at=now,
    )
    await service.db.create_profile(profile)
    action = ActionPlan(
        action_id="a", type="finalize", success_condition="ok", recovery_strategy="none",
        retry=RetryPolicy(max_attempts=1),
    )
    run = RunRecord(
        run_id="old-run", protocol_id="p", protocol_version="1", protocol_hash="h", input_values={}, input_hash="i",
        profile_id=profile.profile_id, provider="generic", conversation_mode=ConversationMode.NEW,
        config_hash="c", config_snapshot={}, component_versions={}, state=RunState.QUEUED,
        plan=ExecutionPlan(actions=(action,)), created_at=now, updated_at=now,
    )
    await service.db.create_run(run)
    await service.db.transition_run(run.run_id, RunState.RUNNING)
    await service.db.transition_run(run.run_id, RunState.COMPLETED)
    old = (now - timedelta(days=365)).isoformat()
    conn = sqlite3.connect(config.db_path)
    conn.execute("UPDATE runs SET created_at=?,updated_at=? WHERE run_id=?", (old, old, run.run_id))
    conn.execute("UPDATE events SET timestamp=? WHERE run_id=?", (old, run.run_id))
    conn.commit(); conn.close()

    preview = await service.cleanup(apply=False)
    assert run.run_id in preview["runs"]
    await service.cleanup(apply=True)
    assert await service.db.get_run(run.run_id) is None
    assert await service.db.get_profile(profile.profile_id) is not None
