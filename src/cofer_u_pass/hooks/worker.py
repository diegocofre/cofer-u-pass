from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path


def resolve(ref: str):
    if ":" not in ref:
        raise ValueError("hook reference must be module:function")
    module_name, function_name = ref.split(":", 1)
    module = importlib.import_module(module_name)
    fn = getattr(module, function_name)
    if not callable(fn):
        raise TypeError(f"hook is not callable: {ref}")
    return fn


async def run(ref: str, input_path: Path, output_path: Path) -> None:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    fn = resolve(ref)
    result = fn(payload)
    if asyncio.iscoroutine(result):
        result = await result
    output_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(run(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])))
