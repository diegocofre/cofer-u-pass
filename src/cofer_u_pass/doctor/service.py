from __future__ import annotations

import json
import os
import re
import shutil
import sys
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cofer_u_pass.adapters.registry import AdapterRegistry
from cofer_u_pass.browser.runtime import BrowserRuntime
from cofer_u_pass.config.settings import AppConfig
from cofer_u_pass.persistence.database import Database, SCHEMA_VERSION

SENSITIVE = re.compile(r"(token|password|secret|authorization|cookie|session|mfa|captcha|bearer)", re.I)


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if SENSITIVE.search(str(k)):
                out[k] = "<redacted>"
            else:
                out[k] = sanitize(v)
        return out
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer <redacted>", value)
        return value[:20000]
    return value


class DoctorService:
    def __init__(self, config: AppConfig, db: Database):
        self.config = config
        self.db = db
        self.registry = AdapterRegistry()
        self.runtime = BrowserRuntime(config)

    async def preventive(self) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        def add(name: str, ok: bool, detail: str) -> None:
            checks.append({"name": name, "ok": ok, "detail": detail})

        add("python", sys.version_info >= (3, 11), sys.version.split()[0])
        add("api_loopback", self.config.api.host in {"127.0.0.1", "::1", "localhost"}, self.config.api.host)
        for label, path in [
            ("data_root", self.config.data_path), ("profiles", self.config.profiles_path),
            ("artifacts", self.config.artifacts_path), ("evidence", self.config.evidence_path),
        ]:
            add(label, path.exists() and os.access(path, os.R_OK | os.W_OK), str(path))
        ok, detail = await self.db.integrity_check()
        add("sqlite_integrity", ok, detail)
        version = await self.db.schema_version()
        add("sqlite_schema", version == SCHEMA_VERSION, f"installed={version} expected={SCHEMA_VERSION}")
        usage = shutil.disk_usage(self.config.data_path)
        add("disk_space", usage.free >= 128 * 1024 * 1024, f"free={usage.free} bytes")
        try:
            exe = await self.runtime.chromium_executable()
            add("chromium", exe is not None, str(exe) if exe else "not installed; run setup")
        except Exception as exc:
            add("chromium", False, str(exc))
        leases = await self.db.leases()
        add("leases", True, f"{len(leases)} active lease record(s)")
        for profile in await self.db.list_profiles():
            p = Path(profile.profile_dir)
            perms_ok = p.exists() and os.access(p, os.R_OK | os.W_OK)
            add(f"profile:{profile.profile_id}", perms_ok, f"provider={profile.provider} status={profile.status}")
        for provider in self.registry.providers():
            try:
                adapter = self.registry.create(provider)
                add(f"adapter:{provider}", bool(adapter.capabilities), f"adapter={adapter.adapter_version} rules={adapter.rules.version}")
            except Exception as exc:
                add(f"adapter:{provider}", False, str(exc))
        return checks

    async def capture_basic(self, run_id: str, failure_class: str, message: str) -> str:
        run = await self.db.get_run(run_id)
        if not run:
            raise KeyError(run_id)
        package_id = str(uuid.uuid4())
        root = self.config.evidence_path / run_id / package_id
        root.mkdir(parents=True, exist_ok=True)
        events = await self.db.get_events(run_id, max(0, 0), 5000)
        actions = await self.db.get_actions(run_id)
        files = {
            "run.json": sanitize(run.model_dump(mode="json")),
            "events.json": sanitize([e.model_dump(mode="json") for e in events[-200:]]),
            "actions.json": sanitize(actions),
            "failure.json": sanitize({"failure_class": failure_class, "message": message}),
        }
        hashes: dict[str, str] = {}
        import hashlib
        for name, payload in files.items():
            data = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
            (root / name).write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        manifest = {
            "schema_version": "1.0", "package_id": package_id, "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(), "files": hashes,
            "redaction": "allowlisted runtime metadata; sensitive-key and bearer redaction applied",
        }
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        await self.db.append_event(run_id, "doctor.evidence_created", {"package_id": package_id, "path": str(root)})
        return str(root)

    async def capture_incident(self, run_id: str, failure_class: str, message: str, page=None) -> str:
        package_path = Path(await self.capture_basic(run_id, failure_class, message))
        if page is not None and self.config.doctor.dom_fragments:
            try:
                structure = await page.evaluate("""() => {
                  const nodes = [];
                  const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_ELEMENT);
                  let n;
                  while ((n = walker.nextNode()) && nodes.length < 250) {
                    const item = {
                      tag: n.tagName.toLowerCase(),
                      role: n.getAttribute('role'),
                      ariaLabel: n.getAttribute('aria-label'),
                      testId: n.getAttribute('data-testid'),
                      contentEditable: n.getAttribute('contenteditable'),
                      inputType: n.tagName === 'INPUT' ? n.getAttribute('type') : null
                    };
                    nodes.push(item);
                  }
                  return {url: location.origin + location.pathname, title: document.title, nodes};
                }""")
                data = json.dumps(sanitize(structure), ensure_ascii=False, indent=2).encode("utf-8")
                path = package_path / "dom-structure.json"
                path.write_bytes(data)
                import hashlib
                manifest_path = package_path / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["files"][path.name] = hashlib.sha256(data).hexdigest()
                manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            except Exception:
                pass
        return str(package_path)

    def inventory(self, package_dir: Path) -> list[dict[str, Any]]:
        package_dir = package_dir.resolve(strict=True)
        root = self.config.evidence_path.resolve()
        if root not in package_dir.parents:
            raise ValueError("diagnostic package is outside evidence root")
        return [{"name": p.name, "size": p.stat().st_size} for p in sorted(package_dir.iterdir()) if p.is_file()]

    def export(self, package_dir: Path, target: Path) -> Path:
        package_dir = package_dir.resolve(strict=True)
        root = self.config.evidence_path.resolve()
        if root not in package_dir.parents:
            raise ValueError("diagnostic package is outside evidence root")
        target = target.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in package_dir.iterdir():
                if p.is_file():
                    zf.write(p, p.name)
        return target
