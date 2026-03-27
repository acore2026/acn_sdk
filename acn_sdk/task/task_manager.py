from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable


class TaskManager:
    def __init__(self, max_workers: int = 4) -> None:
        self._logger = logging.getLogger(self.__class__.__name__)
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._tasks: dict[str, Future[Any]] = {}

    def submit(self, task_name: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Future[Any]:
        future = self._executor.submit(func, *args, **kwargs)
        self._tasks[task_name] = future
        self._logger.info("Submitted task %s", task_name)
        return future

    def stop_all(self) -> None:
        self._logger.info("Stopping all tasks: %s", list(self._tasks))
        for future in self._tasks.values():
            future.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._tasks.clear()
