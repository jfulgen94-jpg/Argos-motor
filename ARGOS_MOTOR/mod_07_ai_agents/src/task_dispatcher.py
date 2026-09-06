"""Asynchronous task queue dispatcher for batch AI processing."""
import asyncio
from typing import Callable, Any, List


class TaskDispatcher:
    def __init__(self, max_concurrent_tasks: int = 4):
        self.semaphore = asyncio.Semaphore(max_concurrent_tasks)

    async def execute_task(self, task_fn: Callable[..., Any], *args, **kwargs) -> Any:
        async with self.semaphore:
            return await task_fn(*args, **kwargs)
