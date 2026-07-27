from __future__ import annotations

import asyncio

import pytest

from cofer_u_pass.application.service import ApplicationService


@pytest.mark.asyncio
async def test_wait_for_execution_cleanup_waits_for_executor_task(config):
    service = ApplicationService(config)
    finished = False

    async def executor_tail():
        nonlocal finished
        await asyncio.sleep(0.02)
        finished = True

    task = asyncio.create_task(executor_tail())
    service._tasks["run"] = task

    await service.wait_for_execution_cleanup("run")

    assert finished is True
    assert task.done() is True
