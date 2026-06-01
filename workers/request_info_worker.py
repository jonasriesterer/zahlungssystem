"""Camunda 8 Cloud worker for request-info jobs."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Mapping

from utils import StructuredLogger
from workers.errors import CamundaJobValidationError
from workers.job_types import REQUEST_INFO_JOB_TYPE
from workers.runtime import (
    create_job_worker,
    get_job_variables,
    map_job_exception,
    publish_camunda_message,
    run_worker,
)
from camunda_orchestration_sdk.runtime.job_worker import JobContext


logger = StructuredLogger.for_module(__name__)


class RequestInfoValidationError(CamundaJobValidationError):
    """Raised when the incoming request-info payload is incomplete."""

    error_code = "REQUEST_INFO_VALIDATION_ERROR"


@dataclass(frozen=True)
class RequestInfoPayload:
    """Validated payload extracted from a Camunda job."""

    simulate_delay: bool
    store_id: str


def _as_mapping(value: Any) -> Mapping[str, Any]:
    """Return a plain mapping from dict-like SDK values."""

    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if isinstance(value, Mapping):
        return value
    return {}


def _as_bool(value: Any, default: bool = False) -> bool:
    """Normalize boolean-like Camunda variables."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off", ""}:
            return False
    return default


def _parse_payload(job : JobContext) -> RequestInfoPayload:
    """Validate and normalize the nested `data` payload."""

    variables = get_job_variables(job)
    data = _as_mapping(variables.get("data"))
    if not data:
        raise RequestInfoValidationError("data-Objekt fehlt in den Job-Variablen")

    store_id = str(data.get("storeId") or "").strip()
    
    if not store_id:
        raise RequestInfoValidationError("data.storeId fehlt oder ist leer")

    return RequestInfoPayload(
        simulate_delay=_as_bool(data.get("simulateDelay"), default=False),
        store_id=store_id,
    )


def _build_response(payload: RequestInfoPayload) -> dict[str, Any]:
    """Convert the request into a Camunda-friendly acknowledgement."""

    return {
        "success": True,
        "message": "Request info job completed",
        "jobType": REQUEST_INFO_JOB_TYPE,
        "simulateDelay": payload.simulate_delay,
        "storeId": payload.store_id,
        "messagePublished": not payload.simulate_delay,
        "status": "message_published" if not payload.simulate_delay else "delay_simulated",
    }


async def _request_info_handler(job : JobContext) -> dict[str, Any]:
    """Handle the `request-info` Camunda job."""

    try:
        payload = _parse_payload(job)
        logger.log_debug(
            "Processing request-info job",
            store_id=payload.store_id,
            simulate_delay=payload.simulate_delay,
        )

        if not payload.simulate_delay:
            await publish_camunda_message(
                name="Message_InfoReceived",
                correlation_key=payload.store_id,
                logger=logger,
            )
            logger.log_debug(
                "Published info received message",
                store_id=payload.store_id,
                message_name="Message_InfoReceived",
            )
        else:
            logger.log_debug(
                "Skipping info message publication due to simulated delay",
                store_id=payload.store_id,
            )

        logger.log_info(
            "Request-info successfully processed",
            job_type=REQUEST_INFO_JOB_TYPE,
            store_id=payload.store_id,
            simulate_delay=payload.simulate_delay,
        )

        return _build_response(payload)
    except RequestInfoValidationError as exc:
        map_job_exception(
            exc,
            job,
            job_label="Request info job",
            technical_message="Technischer Fehler beim Verarbeiten der Info-Anfrage",
            logger=logger,
        )


def create_worker():
    """Create and configure the request-info worker instance."""

    worker_name = REQUEST_INFO_JOB_TYPE + "-worker"
    fetch_vars = ["data"]

    return create_job_worker(
        job_type=REQUEST_INFO_JOB_TYPE,
        task_handler=_request_info_handler,
        timeout_ms=int(os.getenv("CAMUNDA_WORKER_TIMEOUT", "20000")),
        fetch_variables=fetch_vars,
        worker_name=worker_name,
    )


async def run_worker_instance() -> None:
    """Start the worker loop and keep polling for request-info jobs."""

    worker = create_worker()
    await run_worker(worker, job_type=REQUEST_INFO_JOB_TYPE, logger=logger)


def main() -> None:
    """Entrypoint for `python -m workers.request_info_worker`."""

    asyncio.run(run_worker_instance())


if __name__ == "__main__":
    main()
