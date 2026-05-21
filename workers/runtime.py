"""Shared runtime helpers for Camunda workers."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Callable, Mapping

from camunda_orchestration_sdk import CamundaAsyncClient
from camunda_orchestration_sdk.runtime.job_worker import (
    JobContext,
    JobError,
    JobFailure,
    JobWorker,
    WorkerConfig,
)

from .errors import CamundaJobError, CamundaJobTechnicalError


def create_job_worker(
    job_type: str,
    task_handler: Callable[[JobContext], Any],
    *,
    timeout_ms: int = 20000,
    fetch_variables: list[str] | None = None,
    worker_name: str | None = None,
    max_concurrent_jobs: int | None = None,
) -> JobWorker:
    """Create a configured `JobWorker` instance."""

    if timeout_ms is None:
        timeout_env = os.getenv("CAMUNDA_WORKER_TIMEOUT")
        if timeout_env is None:
            raise ValueError(
                "job_timeout_milliseconds is required (timeout_ms arg or CAMUNDA_WORKER_TIMEOUT env)"
            )
        timeout_ms = int(timeout_env)

    cfg = WorkerConfig(
        job_type=job_type,
        job_timeout_milliseconds=timeout_ms,
        fetch_variables=fetch_variables,
        worker_name=worker_name,
        max_concurrent_jobs=max_concurrent_jobs,
    )

    camunda_client = CamundaAsyncClient()

    return JobWorker(client=camunda_client, callback=task_handler, config=cfg)


def get_job_variables(job: JobContext) -> Mapping[str, Any]:
    """Return job variables as a plain mapping."""

    variables = getattr(job, "variables", {})
    if hasattr(variables, "to_dict"):
        return variables.to_dict()
    if isinstance(variables, Mapping):
        return variables
    return {}


def get_zeebe_address() -> str:
    """Resolve the configured Zeebe endpoint for logging."""

    if os.getenv("CAMUNDA_CLIENT_MODE", "").lower() == "saas":
        cluster_id = os.getenv("CAMUNDA_CLIENT_CLOUD_CLUSTER_ID", "unknown")
        region = os.getenv("CAMUNDA_CLIENT_CLOUD_REGION", "unknown")
        return f"{cluster_id}.{region}.zeebe.camunda.io:443"
    return os.getenv("ZEEBE_GRPC_ADDRESS", "localhost:26500")


def map_job_exception(
    exception: Exception,
    job: JobContext,
    *,
    job_label: str,
    technical_message: str,
    logger,
) -> None:
    """Translate internal exceptions into Camunda job outcomes."""

    variables = get_job_variables(job)
    job_id = str(
        variables.get("invoiceID")
        or variables.get("requestId")
        or variables.get("correlationId")
        or variables.get("jobId")
        or "unknown"
    )

    if isinstance(exception, CamundaJobError) and not isinstance(
        exception, CamundaJobTechnicalError
    ):
        logger.log_warning(
            f"{job_label} rejected",
            job_id=job_id,
            error_code=exception.error_code,
            reason=str(exception),
        )
        raise JobError(exception.error_code, str(exception))

    logger.log_error(
        f"{job_label} failed technically",
        exc_info=exception,
        job_id=job_id,
    )
    raise JobFailure(technical_message, retries=None)


async def keep_worker_alive() -> None:
    """Block forever after a worker has been started."""

    await asyncio.Event().wait()


async def run_worker(worker: JobWorker, *, job_type: str, logger) -> None:
    """Start a worker and keep the process alive."""

    logger.log_debug(
        "Starting Camunda worker",
        task_type=job_type,
        zeebe_address=get_zeebe_address(),
        worker_name=worker.config.worker_name,
    )
    worker.start()
    await keep_worker_alive()
