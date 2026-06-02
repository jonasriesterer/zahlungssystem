"""Shared runtime helpers for Camunda workers."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Callable, Mapping

from camunda_orchestration_sdk import CamundaAsyncClient
from camunda_orchestration_sdk.api.message.publish_message import MessagePublicationRequest
from camunda_orchestration_sdk.models.message_publication_request_variables import (
    MessagePublicationRequestVariables,
)
from camunda_orchestration_sdk.errors import ApiError
from camunda_orchestration_sdk.runtime.job_worker import (
    JobContext,
    JobError,
    JobFailure,
    JobWorker,
    WorkerConfig,
)
from httpx import TimeoutException as HttpxTimeoutException

from .errors import CamundaJobError, CamundaJobTechnicalError


def _patch_camunda_sdk_job_activation_parsing() -> None:
    """Work around SDK parsing issues for optional job fields in activate_jobs."""

    try:
        from camunda_orchestration_sdk.models import job_activation_result as model
        from camunda_orchestration_sdk.models.activated_job_result import (
            ActivatedJobResult,
        )
    except Exception:
        return

    if getattr(model.JobActivationResult, "_rechnungsbearbeitung_patch", False):
        return

    original_from_dict = model.JobActivationResult.from_dict.__func__

    @classmethod
    def patched_from_dict(cls, src_dict):
        d = dict(src_dict)
        jobs: list[ActivatedJobResult] = []
        for jobs_item_data in d.pop("jobs"):
            item = dict(jobs_item_data)
            item.setdefault("userTask", None)
            item.setdefault("tags", [])
            item.setdefault("rootProcessInstanceKey", None)
            jobs.append(ActivatedJobResult.from_dict(item))

        result = cls(jobs=jobs)
        result.additional_properties = d
        return result

    model.JobActivationResult.from_dict = patched_from_dict
    model.JobActivationResult._rechnungsbearbeitung_patch = True
    model.JobActivationResult._rechnungsbearbeitung_original_from_dict = (
        original_from_dict
    )


def _apply_camunda_env_compatibility() -> None:
    """Map legacy Camunda env vars to the SDK v9 configuration keys.

    The project historically used `CAMUNDA_CLIENT_MODE=saas` plus cloud-specific
    variables. SDK v9 expects REST + auth strategy variables instead.
    """

    client_id = os.getenv("CAMUNDA_CLIENT_ID") or os.getenv(
        "CAMUNDA_CLIENT_AUTH_CLIENTID"
    )
    legacy_client_id = os.getenv("CAMUNDA_CLIENT_AUTH_CLIENT_ID")
    if not client_id and legacy_client_id:
        os.environ["CAMUNDA_CLIENT_ID"] = legacy_client_id
        os.environ["CAMUNDA_CLIENT_AUTH_CLIENTID"] = legacy_client_id

    client_secret = os.getenv("CAMUNDA_CLIENT_SECRET") or os.getenv(
        "CAMUNDA_CLIENT_AUTH_CLIENTSECRET"
    )
    legacy_client_secret = os.getenv("CAMUNDA_CLIENT_AUTH_CLIENT_SECRET")
    if not client_secret and legacy_client_secret:
        os.environ["CAMUNDA_CLIENT_SECRET"] = legacy_client_secret
        os.environ["CAMUNDA_CLIENT_AUTH_CLIENTSECRET"] = legacy_client_secret

    if os.getenv("CAMUNDA_CLIENT_MODE", "").lower() == "saas":
        cluster_id = os.getenv("CAMUNDA_CLIENT_CLOUD_CLUSTER_ID")
        region = os.getenv("CAMUNDA_CLIENT_CLOUD_REGION")
        if cluster_id and region:
            modern_saas_rest = f"https://{region}.zeebe.camunda.io/{cluster_id}/v2"
            rest_address = os.getenv("CAMUNDA_REST_ADDRESS", "").strip()
            legacy_host = f"{cluster_id}.{region}.zeebe.camunda.io"

            if not rest_address:
                os.environ["CAMUNDA_REST_ADDRESS"] = modern_saas_rest
            elif legacy_host in rest_address:
                # Backward compatibility: convert gRPC-style SaaS host to REST v2 URL.
                os.environ["CAMUNDA_REST_ADDRESS"] = modern_saas_rest

    if (
        not os.getenv("CAMUNDA_AUTH_STRATEGY")
        and os.getenv("CAMUNDA_CLIENT_ID")
        and os.getenv("CAMUNDA_CLIENT_SECRET")
    ):
        os.environ["CAMUNDA_AUTH_STRATEGY"] = "OAUTH"


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

    _patch_camunda_sdk_job_activation_parsing()
    _apply_camunda_env_compatibility()

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

    rest_address = os.getenv("CAMUNDA_REST_ADDRESS")
    if rest_address:
        return rest_address

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


async def publish_camunda_message(
    *,
    name: str,
    correlation_key: str,
    variables: Mapping[str, Any] | None = None,
    logger,
    time_to_live: int = 60_000,
) -> Any:
    """Publish a Camunda message with shared SDK error handling."""

    _patch_camunda_sdk_job_activation_parsing()
    _apply_camunda_env_compatibility()

    client = CamundaAsyncClient()
    try:
        message_variables = MessagePublicationRequestVariables.from_dict(
            dict(variables or {})
        )
        request = MessagePublicationRequest(
            name=name,
            correlation_key=correlation_key,
            time_to_live=time_to_live,
            variables=message_variables,
        )
        return await client.publish_message(data=request)
    except (ApiError, HttpxTimeoutException) as exc:
        logger.log_error(
            "Failed to publish Camunda message",
            exc_info=exc,
            message_name=name,
            correlation_key=correlation_key,
        )
        raise JobFailure(
            "Technischer Fehler beim Senden der Camunda-Nachricht",
            retries=None,
        ) from exc
