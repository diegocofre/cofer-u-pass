from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

from cofer_u_pass.domain.models import (
    ActionPlan,
    ActionState,
    CanonicalResult,
    Checkpoint,
    EventEnvelope,
    FailureClass,
    ProfileRecord,
    RunRecord,
    RunState,
    assert_run_transition,
)

T = TypeVar("T")
SCHEMA_VERSION = 1

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
  profile_id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  profile_dir TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,
  authenticated INTEGER NOT NULL DEFAULT 0,
  chromium_version TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  protocol_id TEXT NOT NULL,
  protocol_version TEXT NOT NULL,
  protocol_hash TEXT NOT NULL,
  input_json TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  profile_id TEXT NOT NULL REFERENCES profiles(profile_id),
  provider TEXT NOT NULL,
  conversation_mode TEXT NOT NULL,
  conversation_id TEXT,
  client_request_id TEXT,
  config_hash TEXT NOT NULL,
  config_json TEXT NOT NULL,
  component_versions_json TEXT NOT NULL,
  state TEXT NOT NULL,
  plan_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  error_class TEXT,
  error_message TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_run_idempotency
ON runs(profile_id, protocol_id, client_request_id)
WHERE client_request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_runs_state ON runs(state, created_at);
CREATE TABLE IF NOT EXISTS actions (
  run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  action_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  type TEXT NOT NULL,
  state TEXT NOT NULL,
  plan_json TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 0,
  started_at TEXT,
  confirmed_at TEXT,
  error_class TEXT,
  error_message TEXT,
  evidence_json TEXT,
  PRIMARY KEY(run_id, action_id)
);
CREATE TABLE IF NOT EXISTS events (
  run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  event_id TEXT PRIMARY KEY,
  sequence INTEGER NOT NULL,
  timestamp TEXT NOT NULL,
  type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  UNIQUE(run_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_events_run_sequence ON events(run_id, sequence);
CREATE TABLE IF NOT EXISTS checkpoints (
  checkpoint_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  action_id TEXT NOT NULL,
  checkpoint_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_run ON checkpoints(run_id, created_at);
CREATE TABLE IF NOT EXISTS results (
  run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  action_id TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
  conversation_id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES profiles(profile_id),
  provider TEXT NOT NULL,
  external_id TEXT,
  url TEXT,
  imported INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leases (
  profile_id TEXT PRIMARY KEY REFERENCES profiles(profile_id),
  run_id TEXT,
  pid INTEGER NOT NULL,
  heartbeat TEXT NOT NULL,
  acquired_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS backups (
  backup_id TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  schema_version INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
"""


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads(value: str | None, default: Any = None) -> Any:
    return json.loads(value) if value is not None else default


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._thread_lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    async def _call(self, fn: Callable[[], T]) -> T:
        return await asyncio.to_thread(fn)

    async def initialize(self) -> None:
        def op() -> None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._thread_lock, self._connect() as conn:
                meta_exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'"
                ).fetchone() is not None
                if meta_exists:
                    row = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
                    if not row:
                        raise RuntimeError("database has schema_meta but no schema_version")
                    installed = int(row[0])
                    if installed > SCHEMA_VERSION:
                        raise RuntimeError(
                            f"database schema {installed} is newer than supported schema {SCHEMA_VERSION}; "
                            "install a compatible package or restore its matching backup"
                        )
                    if installed < SCHEMA_VERSION:
                        raise RuntimeError(
                            f"database schema {installed} requires a migration path not present in this build"
                        )
                    conn.executescript(SCHEMA_SQL)
                    return
                existing_tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                if existing_tables:
                    raise RuntimeError("refusing to initialize an unversioned non-empty SQLite database")
                conn.executescript(SCHEMA_SQL)
                conn.execute(
                    "INSERT INTO schema_meta(key,value) VALUES('schema_version',?)",
                    (str(SCHEMA_VERSION),),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO migrations(version,applied_at) VALUES(?,?)",
                    (SCHEMA_VERSION, _utc()),
                )
        await self._call(op)

    async def integrity_check(self) -> tuple[bool, str]:
        def op() -> tuple[bool, str]:
            with self._connect() as conn:
                row = conn.execute("PRAGMA integrity_check").fetchone()
                text = str(row[0]) if row else "unknown"
                return text.lower() == "ok", text
        return await self._call(op)

    async def schema_version(self) -> int:
        def op() -> int:
            with self._connect() as conn:
                row = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
                return int(row[0]) if row else 0
        return await self._call(op)

    async def create_backup(self, backups_dir: Path) -> Path:
        def op() -> Path:
            backups_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            target = backups_dir / f"cofer-u-pass-schema{SCHEMA_VERSION}-{ts}.sqlite3"
            with self._thread_lock, self._connect() as source:
                dest = sqlite3.connect(target)
                try:
                    source.backup(dest)
                finally:
                    dest.close()
                bid = str(uuid.uuid4())
                source.execute(
                    "INSERT INTO backups(backup_id,path,schema_version,created_at) VALUES(?,?,?,?)",
                    (bid, str(target), SCHEMA_VERSION, _utc()),
                )
            return target
        return await self._call(op)

    async def create_profile(self, profile: ProfileRecord) -> None:
        def op() -> None:
            with self._thread_lock, self._connect() as conn:
                conn.execute(
                    """INSERT INTO profiles(profile_id,provider,profile_dir,status,authenticated,chromium_version,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        profile.profile_id, profile.provider, profile.profile_dir, profile.status,
                        int(profile.authenticated), profile.chromium_version,
                        profile.created_at.isoformat(), profile.updated_at.isoformat(),
                    ),
                )
        await self._call(op)

    async def update_profile(self, profile_id: str, **fields: Any) -> None:
        allowed = {"status", "authenticated", "chromium_version"}
        invalid = set(fields) - allowed
        if invalid:
            raise ValueError(f"invalid profile fields: {sorted(invalid)}")
        def op() -> None:
            with self._thread_lock, self._connect() as conn:
                parts, values = [], []
                for key, value in fields.items():
                    parts.append(f"{key}=?")
                    values.append(int(value) if key == "authenticated" else value)
                parts.append("updated_at=?")
                values.extend([_utc(), profile_id])
                cur = conn.execute(f"UPDATE profiles SET {', '.join(parts)} WHERE profile_id=?", values)
                if cur.rowcount != 1:
                    raise KeyError(profile_id)
        await self._call(op)

    async def get_profile(self, profile_id: str) -> ProfileRecord | None:
        def op() -> ProfileRecord | None:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM profiles WHERE profile_id=?", (profile_id,)).fetchone()
                if not row:
                    return None
                return ProfileRecord(
                    profile_id=row["profile_id"], provider=row["provider"], profile_dir=row["profile_dir"],
                    status=row["status"], authenticated=bool(row["authenticated"]),
                    chromium_version=row["chromium_version"], created_at=row["created_at"], updated_at=row["updated_at"],
                )
        return await self._call(op)

    async def list_profiles(self) -> list[ProfileRecord]:
        def op() -> list[ProfileRecord]:
            with self._connect() as conn:
                rows = conn.execute("SELECT * FROM profiles ORDER BY created_at").fetchall()
                return [ProfileRecord(
                    profile_id=r["profile_id"], provider=r["provider"], profile_dir=r["profile_dir"],
                    status=r["status"], authenticated=bool(r["authenticated"]), chromium_version=r["chromium_version"],
                    created_at=r["created_at"], updated_at=r["updated_at"],
                ) for r in rows]
        return await self._call(op)

    async def create_run(self, run: RunRecord) -> RunRecord:
        def op() -> RunRecord:
            with self._thread_lock, self._connect() as conn:
                if run.client_request_id:
                    existing = conn.execute(
                        "SELECT run_id FROM runs WHERE profile_id=? AND protocol_id=? AND client_request_id=?",
                        (run.profile_id, run.protocol_id, run.client_request_id),
                    ).fetchone()
                    if existing:
                        row = self._get_run_sync(conn, existing["run_id"])
                        assert row is not None
                        return row
                conn.execute("BEGIN IMMEDIATE")
                try:
                    conn.execute(
                        """INSERT INTO runs(run_id,protocol_id,protocol_version,protocol_hash,input_json,input_hash,profile_id,
                        provider,conversation_mode,conversation_id,client_request_id,config_hash,config_json,component_versions_json,
                        state,plan_json,created_at,updated_at,error_class,error_message)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            run.run_id, run.protocol_id, run.protocol_version, run.protocol_hash,
                            json.dumps(run.input_values, sort_keys=True), run.input_hash, run.profile_id, run.provider,
                            run.conversation_mode.value, run.conversation_id, run.client_request_id, run.config_hash,
                            json.dumps(run.config_snapshot, sort_keys=True), json.dumps(run.component_versions, sort_keys=True),
                            run.state.value, run.plan.model_dump_json(), run.created_at.isoformat(), run.updated_at.isoformat(),
                            None, None,
                        ),
                    )
                    for ordinal, action in enumerate(run.plan.actions):
                        conn.execute(
                            "INSERT INTO actions(run_id,action_id,ordinal,type,state,plan_json) VALUES(?,?,?,?,?,?)",
                            (run.run_id, action.action_id, ordinal, action.type, ActionState.PLANNED.value, action.model_dump_json()),
                        )
                    self._append_event_sync(conn, run.run_id, "run.created", {"state": run.state.value})
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                return run
        return await self._call(op)

    def _get_run_sync(self, conn: sqlite3.Connection, run_id: str) -> RunRecord | None:
        r = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not r:
            return None
        return RunRecord(
            run_id=r["run_id"], protocol_id=r["protocol_id"], protocol_version=r["protocol_version"],
            protocol_hash=r["protocol_hash"], input_values=_loads(r["input_json"], {}), input_hash=r["input_hash"],
            profile_id=r["profile_id"], provider=r["provider"], conversation_mode=r["conversation_mode"],
            conversation_id=r["conversation_id"], client_request_id=r["client_request_id"], config_hash=r["config_hash"],
            config_snapshot=_loads(r["config_json"], {}), component_versions=_loads(r["component_versions_json"], {}),
            state=r["state"], plan=json.loads(r["plan_json"]), created_at=r["created_at"], updated_at=r["updated_at"],
            error_class=r["error_class"], error_message=r["error_message"],
        )

    async def get_run(self, run_id: str) -> RunRecord | None:
        def op() -> RunRecord | None:
            with self._connect() as conn:
                return self._get_run_sync(conn, run_id)
        return await self._call(op)

    async def list_runs(self, states: set[RunState] | None = None) -> list[RunRecord]:
        def op() -> list[RunRecord]:
            with self._connect() as conn:
                if states:
                    q = ",".join("?" for _ in states)
                    rows = conn.execute(f"SELECT run_id FROM runs WHERE state IN ({q}) ORDER BY created_at", tuple(s.value for s in states)).fetchall()
                else:
                    rows = conn.execute("SELECT run_id FROM runs ORDER BY created_at DESC").fetchall()
                return [self._get_run_sync(conn, r["run_id"]) for r in rows]  # type: ignore[list-item]
        return await self._call(op)

    async def transition_run(
        self,
        run_id: str,
        target: RunState,
        *,
        event_type: str = "run.state",
        payload: dict[str, Any] | None = None,
        error_class: FailureClass | None = None,
        error_message: str | None = None,
    ) -> EventEnvelope:
        def op() -> EventEnvelope:
            with self._thread_lock, self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    row = conn.execute("SELECT state FROM runs WHERE run_id=?", (run_id,)).fetchone()
                    if not row:
                        raise KeyError(run_id)
                    current = RunState(row["state"])
                    if current != target:
                        assert_run_transition(current, target)
                    conn.execute(
                        "UPDATE runs SET state=?,updated_at=?,error_class=?,error_message=? WHERE run_id=?",
                        (target.value, _utc(), error_class.value if error_class else None, error_message, run_id),
                    )
                    ev = self._append_event_sync(conn, run_id, event_type, {"state": target.value, **(payload or {})})
                    conn.execute("COMMIT")
                    return ev
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
        return await self._call(op)

    def _append_event_sync(self, conn: sqlite3.Connection, run_id: str, event_type: str, payload: dict[str, Any]) -> EventEnvelope:
        row = conn.execute("SELECT COALESCE(MAX(sequence),0)+1 AS seq FROM events WHERE run_id=?", (run_id,)).fetchone()
        seq = int(row["seq"])
        event = EventEnvelope(
            run_id=run_id,
            event_id=str(uuid.uuid4()),
            sequence=seq,
            timestamp=datetime.now(timezone.utc),
            type=event_type,
            payload=payload,
        )
        conn.execute(
            "INSERT INTO events(run_id,event_id,sequence,timestamp,type,payload_json) VALUES(?,?,?,?,?,?)",
            (run_id, event.event_id, event.sequence, event.timestamp.isoformat(), event.type, json.dumps(payload, sort_keys=True)),
        )
        return event

    async def append_event(self, run_id: str, event_type: str, payload: dict[str, Any] | None = None) -> EventEnvelope:
        def op() -> EventEnvelope:
            with self._thread_lock, self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    ev = self._append_event_sync(conn, run_id, event_type, payload or {})
                    conn.execute("COMMIT")
                    return ev
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
        return await self._call(op)

    async def get_events(self, run_id: str, after_sequence: int = 0, limit: int = 500) -> list[EventEnvelope]:
        def op() -> list[EventEnvelope]:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                    (run_id, after_sequence, limit),
                ).fetchall()
                return [EventEnvelope(
                    run_id=r["run_id"], event_id=r["event_id"], sequence=r["sequence"], timestamp=r["timestamp"],
                    type=r["type"], payload=_loads(r["payload_json"], {}),
                ) for r in rows]
        return await self._call(op)

    async def get_event_by_id(self, run_id: str, event_id: str) -> EventEnvelope | None:
        def op() -> EventEnvelope | None:
            with self._connect() as conn:
                r = conn.execute("SELECT * FROM events WHERE run_id=? AND event_id=?", (run_id, event_id)).fetchone()
                return None if not r else EventEnvelope(
                    run_id=r["run_id"], event_id=r["event_id"], sequence=r["sequence"], timestamp=r["timestamp"],
                    type=r["type"], payload=_loads(r["payload_json"], {}),
                )
        return await self._call(op)

    async def get_actions(self, run_id: str) -> list[dict[str, Any]]:
        def op() -> list[dict[str, Any]]:
            with self._connect() as conn:
                rows = conn.execute("SELECT * FROM actions WHERE run_id=? ORDER BY ordinal", (run_id,)).fetchall()
                return [dict(r) | {"plan": json.loads(r["plan_json"]), "evidence": _loads(r["evidence_json"], {})} for r in rows]
        return await self._call(op)

    async def update_action(
        self,
        run_id: str,
        action_id: str,
        state: ActionState,
        *,
        attempt: int | None = None,
        error_class: FailureClass | None = None,
        error_message: str | None = None,
        evidence: dict[str, Any] | None = None,
        event_type: str = "action.state",
    ) -> EventEnvelope:
        def op() -> EventEnvelope:
            with self._thread_lock, self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    row = conn.execute("SELECT attempt FROM actions WHERE run_id=? AND action_id=?", (run_id, action_id)).fetchone()
                    if not row:
                        raise KeyError(action_id)
                    fields = ["state=?", "error_class=?", "error_message=?", "evidence_json=?"]
                    vals: list[Any] = [state.value, error_class.value if error_class else None, error_message, json.dumps(evidence or {}, sort_keys=True)]
                    if attempt is not None:
                        fields.append("attempt=?")
                        vals.append(attempt)
                    if state == ActionState.STARTED:
                        fields.append("started_at=?")
                        vals.append(_utc())
                    if state == ActionState.CONFIRMED:
                        fields.append("confirmed_at=?")
                        vals.append(_utc())
                    vals.extend([run_id, action_id])
                    conn.execute(f"UPDATE actions SET {', '.join(fields)} WHERE run_id=? AND action_id=?", vals)
                    ev = self._append_event_sync(conn, run_id, event_type, {
                        "action_id": action_id, "state": state.value, "attempt": attempt or row["attempt"],
                        **({"error_class": error_class.value, "error": error_message} if error_class else {}),
                    })
                    conn.execute("COMMIT")
                    return ev
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
        return await self._call(op)

    async def confirm_action_with_checkpoint(self, run_id: str, action_id: str, checkpoint: Checkpoint | None, evidence: dict[str, Any]) -> None:
        def op() -> None:
            with self._thread_lock, self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    conn.execute(
                        "UPDATE actions SET state=?,confirmed_at=?,evidence_json=? WHERE run_id=? AND action_id=?",
                        (ActionState.CONFIRMED.value, _utc(), json.dumps(evidence, sort_keys=True), run_id, action_id),
                    )
                    self._append_event_sync(conn, run_id, "action.confirmed", {"action_id": action_id, "evidence": evidence})
                    if checkpoint:
                        conn.execute(
                            "INSERT INTO checkpoints(checkpoint_id,run_id,action_id,checkpoint_json,created_at) VALUES(?,?,?,?,?)",
                            (checkpoint.checkpoint_id, run_id, action_id, checkpoint.model_dump_json(), checkpoint.created_at.isoformat()),
                        )
                        self._append_event_sync(conn, run_id, "checkpoint.created", {
                            "checkpoint_id": checkpoint.checkpoint_id, "action_id": action_id,
                        })
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
        await self._call(op)

    async def latest_checkpoint(self, run_id: str) -> Checkpoint | None:
        def op() -> Checkpoint | None:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT checkpoint_json FROM checkpoints WHERE run_id=? ORDER BY created_at DESC LIMIT 1", (run_id,)
                ).fetchone()
                return Checkpoint.model_validate_json(row[0]) if row else None
        return await self._call(op)

    async def store_result(self, result: CanonicalResult) -> None:
        def op() -> None:
            with self._thread_lock, self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO results(run_id,result_json,created_at) VALUES(?,?,?)",
                    (result.run_id, result.model_dump_json(), _utc()),
                )
        await self._call(op)

    async def get_result(self, run_id: str) -> CanonicalResult | None:
        def op() -> CanonicalResult | None:
            with self._connect() as conn:
                row = conn.execute("SELECT result_json FROM results WHERE run_id=?", (run_id,)).fetchone()
                return CanonicalResult.model_validate_json(row[0]) if row else None
        return await self._call(op)

    async def store_artifact(self, artifact: Any) -> None:
        def op() -> None:
            with self._thread_lock, self._connect() as conn:
                data = artifact.model_dump(mode="json") if hasattr(artifact, "model_dump") else artifact
                conn.execute(
                    "INSERT OR REPLACE INTO artifacts(artifact_id,run_id,action_id,metadata_json,created_at) VALUES(?,?,?,?,?)",
                    (data["artifact_id"], data["run_id"], data["action_id"], json.dumps(data, sort_keys=True), _utc()),
                )
        await self._call(op)

    async def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        def op() -> list[dict[str, Any]]:
            with self._connect() as conn:
                rows = conn.execute("SELECT metadata_json FROM artifacts WHERE run_id=? ORDER BY created_at", (run_id,)).fetchall()
                return [json.loads(r[0]) for r in rows]
        return await self._call(op)

    async def acquire_lease(self, profile_id: str, run_id: str, pid: int) -> None:
        def op() -> None:
            now = _utc()
            with self._thread_lock, self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO leases(profile_id,run_id,pid,heartbeat,acquired_at) VALUES(?,?,?,?,?)",
                    (profile_id, run_id, pid, now, now),
                )
        await self._call(op)

    async def heartbeat_lease(self, profile_id: str, run_id: str) -> None:
        def op() -> None:
            with self._connect() as conn:
                conn.execute("UPDATE leases SET heartbeat=? WHERE profile_id=? AND run_id=?", (_utc(), profile_id, run_id))
        await self._call(op)

    async def release_lease(self, profile_id: str, run_id: str) -> None:
        def op() -> None:
            with self._thread_lock, self._connect() as conn:
                conn.execute("DELETE FROM leases WHERE profile_id=? AND run_id=?", (profile_id, run_id))
        await self._call(op)

    async def leases(self) -> list[dict[str, Any]]:
        def op() -> list[dict[str, Any]]:
            with self._connect() as conn:
                return [dict(r) for r in conn.execute("SELECT * FROM leases ORDER BY acquired_at").fetchall()]
        return await self._call(op)

    async def interrupted_run_candidates(self) -> list[dict[str, Any]]:
        def op() -> list[dict[str, Any]]:
            with self._connect() as conn:
                rows = conn.execute(
                    """SELECT r.run_id,r.profile_id,r.state,p.profile_dir
                    FROM runs r JOIN profiles p ON p.profile_id=r.profile_id
                    WHERE r.state IN ('running','cancelling') ORDER BY r.created_at"""
                ).fetchall()
                return [dict(r) for r in rows]
        return await self._call(op)

    async def recover_interrupted_run(self, run_id: str) -> RunState:
        def op() -> RunState:
            with self._thread_lock, self._connect() as conn:
                row = conn.execute(
                    "SELECT run_id,profile_id,state FROM runs WHERE run_id=? AND state IN ('running','cancelling')",
                    (run_id,),
                ).fetchone()
                if not row:
                    current = conn.execute("SELECT state FROM runs WHERE run_id=?", (run_id,)).fetchone()
                    if not current:
                        raise KeyError(run_id)
                    return RunState(current[0])
                actions = conn.execute(
                    "SELECT state,plan_json FROM actions WHERE run_id=? ORDER BY ordinal DESC", (run_id,)
                ).fetchall()
                uncertain = False
                for action in actions:
                    if action["state"] == ActionState.OUTCOME_UNKNOWN.value:
                        uncertain = True
                        break
                    if action["state"] == ActionState.STARTED.value:
                        plan = ActionPlan.model_validate_json(action["plan_json"])
                        if plan.external_effects:
                            uncertain = True
                            break
                target = RunState.OUTCOME_UNKNOWN if uncertain else RunState.RECOVERABLE
                conn.execute(
                    "UPDATE runs SET state=?,updated_at=?,error_class=?,error_message=? WHERE run_id=?",
                    (
                        target.value, _utc(),
                        (FailureClass.OUTCOME_UNKNOWN if uncertain else FailureClass.ENVIRONMENT).value,
                        "previous process ended while run was active", run_id,
                    ),
                )
                conn.execute("DELETE FROM leases WHERE profile_id=?", (row["profile_id"],))
                self._append_event_sync(conn, run_id, "run.recovered_after_restart", {"state": target.value})
                return target
        return await self._call(op)

    async def register_conversation(self, conversation_id: str, profile_id: str, provider: str, *, external_id: str | None, url: str | None, imported: bool) -> None:
        def op() -> None:
            now = _utc()
            with self._thread_lock, self._connect() as conn:
                conn.execute(
                    """INSERT INTO conversations(conversation_id,profile_id,provider,external_id,url,imported,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(conversation_id) DO UPDATE SET external_id=excluded.external_id,url=excluded.url,updated_at=excluded.updated_at""",
                    (conversation_id, profile_id, provider, external_id, url, int(imported), now, now),
                )
        await self._call(op)

    async def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        def op() -> dict[str, Any] | None:
            with self._connect() as conn:
                r = conn.execute("SELECT * FROM conversations WHERE conversation_id=?", (conversation_id,)).fetchone()
                return dict(r) if r else None
        return await self._call(op)

    async def update_run_component_versions(self, run_id: str, versions: dict[str, str]) -> None:
        def op() -> None:
            with self._thread_lock, self._connect() as conn:
                row = conn.execute("SELECT component_versions_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
                if not row:
                    raise KeyError(run_id)
                current = json.loads(row[0])
                current.update(versions)
                conn.execute(
                    "UPDATE runs SET component_versions_json=?,updated_at=? WHERE run_id=?",
                    (json.dumps(current, sort_keys=True), _utc(), run_id),
                )
        await self._call(op)

    async def set_run_conversation(self, run_id: str, conversation_id: str) -> None:
        def op() -> None:
            with self._thread_lock, self._connect() as conn:
                conn.execute("UPDATE runs SET conversation_id=?,updated_at=? WHERE run_id=?", (conversation_id, _utc(), run_id))
        await self._call(op)

    async def count_events_before(self, cutoff_iso: str) -> int:
        def op() -> int:
            with self._connect() as conn:
                row = conn.execute(
                    """SELECT COUNT(*) FROM events e JOIN runs r ON r.run_id=e.run_id
                    WHERE e.timestamp < ? AND r.state IN ('completed','cancelled','failed')""",
                    (cutoff_iso,),
                ).fetchone()
                return int(row[0])
        return await self._call(op)

    async def delete_events_before(self, cutoff_iso: str) -> int:
        def op() -> int:
            with self._thread_lock, self._connect() as conn:
                cur = conn.execute(
                    """DELETE FROM events WHERE event_id IN (
                      SELECT e.event_id FROM events e JOIN runs r ON r.run_id=e.run_id
                      WHERE e.timestamp < ? AND r.state IN ('completed','cancelled','failed')
                    )""",
                    (cutoff_iso,),
                )
                return cur.rowcount
        return await self._call(op)

    async def delete_run(self, run_id: str) -> None:
        def op() -> None:
            with self._thread_lock, self._connect() as conn:
                row = conn.execute("SELECT state FROM runs WHERE run_id=?", (run_id,)).fetchone()
                if not row:
                    return
                if row[0] not in {'completed', 'cancelled', 'failed'}:
                    raise RuntimeError("only resolved terminal runs may be removed by retention cleanup")
                conn.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
        await self._call(op)

    async def has_active_runs(self) -> bool:
        def op() -> bool:
            with self._connect() as conn:
                row = conn.execute("SELECT 1 FROM runs WHERE state IN ('queued','running','cancelling') LIMIT 1").fetchone()
                return bool(row)
        return await self._call(op)
