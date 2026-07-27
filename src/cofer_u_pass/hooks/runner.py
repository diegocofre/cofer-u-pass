from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from cofer_u_pass.config.settings import AppConfig
from cofer_u_pass.domain.errors import EnvironmentFailure, ProtocolError


class HookRunner:
    def __init__(self, config: AppConfig):
        self.config = config

    async def run(
        self,
        *,
        ref: str,
        payload: dict[str, Any],
        run_dir: Path,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if input_schema:
            errors = list(Draft202012Validator(input_schema).iter_errors(payload))
            if errors:
                raise ProtocolError(f"hook input contract failed: {errors[0].message}")
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if len(encoded) > self.config.hooks.max_input_bytes:
            raise ProtocolError("hook input exceeds configured limit")
        run_dir.mkdir(parents=True, exist_ok=True)
        input_path = run_dir / "hook-input.json"
        output_path = run_dir / "hook-output.json"
        input_path.write_bytes(encoded)
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
            "PYTHONIOENCODING": "utf-8",
        }
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "cofer_u_pass.hooks.worker", ref, str(input_path), str(output_path),
            cwd=str(run_dir), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout or self.config.hooks.timeout_seconds)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise EnvironmentFailure(f"hook timed out: {ref}")
        if proc.returncode != 0:
            err = stderr.decode("utf-8", "replace")[-4000:]
            raise EnvironmentFailure(f"hook failed ({proc.returncode}): {err}")
        if not output_path.exists():
            raise EnvironmentFailure("hook produced no output")
        raw = output_path.read_bytes()
        if len(raw) > self.config.hooks.max_output_bytes:
            raise ProtocolError("hook output exceeds configured limit")
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"hook output is not JSON: {exc}") from exc
        if output_schema:
            errors = list(Draft202012Validator(output_schema).iter_errors(result))
            if errors:
                raise ProtocolError(f"hook output contract failed: {errors[0].message}")
        return {
            "result": result,
            "stdout": stdout.decode("utf-8", "replace")[-4000:],
            "stderr": stderr.decode("utf-8", "replace")[-4000:],
            "exit_code": proc.returncode,
        }
