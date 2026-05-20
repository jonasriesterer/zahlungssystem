"""Camunda worker configuration using camunda_orchestration_sdk.

This module provides a small helper `create_job_worker` that wraps the
`camunda_orchestration_sdk` job worker creation. It supports reading
configuration from environment variables (CAMUNDA_CLIENT_MODE, CAMUNDA_WORKER_*,
CAMUNDA_* auth variables) and keeps the same task decorator semantics as
existing code.
"""

from __future__ import annotations

import os
from typing import Callable

from camunda_orchestration_sdk.runtime.job_worker import (
    JobWorker,
    WorkerConfig,
)
from camunda_orchestration_sdk import CamundaAsyncClient


def create_job_worker(job_type: str, task_handler: Callable, *, timeout_ms: int = 20000, fetch_variables: list[str] | None = None, worker_name: str | None = None, max_concurrent_jobs: int | None = None) -> JobWorker:
    """Create a `JobWorker` using `camunda_orchestration_sdk`.

    Args:
        job_type: Zeebe job type to subscribe to.
        task_handler: Callable handler receiving a `JobContext`.
        timeout_ms: Job timeout in milliseconds (required by SDK).
        fetch_variables: Optional list of variables to activate.
        worker_name: Optional worker name override.
        max_concurrent_jobs: Optional concurrency limit.

    Returns:
        Configured `JobWorker` instance (not started).
    """

    # Ensure we have a timeout value (SDK requires it either via WorkerConfig
    # or via CAMUNDA_WORKER_TIMEOUT env var). Prefer explicit argument.
    if timeout_ms is None:
        timeout_env = os.getenv("CAMUNDA_WORKER_TIMEOUT")
        if timeout_env is None:
            raise ValueError("job_timeout_milliseconds is required (timeout_ms arg or CAMUNDA_WORKER_TIMEOUT env)")
        timeout_ms = int(timeout_env)

    cfg = WorkerConfig(
        job_type=job_type,
        job_timeout_milliseconds=timeout_ms,
        fetch_variables=fetch_variables,
        worker_name=worker_name,
        max_concurrent_jobs=max_concurrent_jobs,
    )

    # Create an async Camunda client (auth providers are configured from env)
    camunda_client = CamundaAsyncClient()

    worker = JobWorker(
        client=camunda_client,
        callback=task_handler,
        config=cfg,
    )

    return worker
