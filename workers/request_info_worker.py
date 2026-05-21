"""Camunda 8 Cloud worker for request-info jobs."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from utils import StructuredLogger
from workers.errors import CamundaJobValidationError
from workers.job_types import REQUEST_INFO_JOB_TYPE
from workers.runtime import create_job_worker, get_job_variables, map_job_exception, run_worker


logger = StructuredLogger.for_module(__name__)


class RequestInfoValidationError(CamundaJobValidationError):
    """Raised when the incoming request-info payload is incomplete."""

    error_code = "REQUEST_INFO_VALIDATION_ERROR"


@dataclass(frozen=True)
class RequestInfoPayload:
    """Validated payload extracted from a Camunda job."""

    request_id: str
    subject: str
    requested_info: str
    recipient: str | None
    context: Any


def _parse_payload(job) -> RequestInfoPayload:
    """Validate and normalize request-info variables."""

    variables = get_job_variables(job)

    requested_info = (
        variables.get("requestedInfo")
        or variables.get("message")
        or variables.get("details")
    )
    if requested_info is None or str(requested_info).strip() == "":
        raise RequestInfoValidationError(
            "requestedInfo, message oder details muss gesetzt sein"
        )

    request_id = str(
        variables.get("requestId")
        or variables.get("correlationId")
        or variables.get("invoiceID")
        or ""
    ).strip()
    subject = str(variables.get("subject") or "additional-information").strip()
    recipient = str(variables.get("recipient") or variables.get("customerEmail") or "").strip()
    context = variables.get("context") or variables.get("metadata") or {}

    if not subject:
        raise RequestInfoValidationError("subject darf nicht leer sein")

    return RequestInfoPayload(
        request_id=request_id,
        subject=subject,
        requested_info=str(requested_info).strip(),
        recipient=recipient or None,
        context=context,
    )


def _build_response(payload: RequestInfoPayload) -> dict[str, Any]:
    """Convert the request into a Camunda-friendly acknowledgement."""

    return {
        "success": True,
        "message": "Information request prepared",
        "jobType": REQUEST_INFO_JOB_TYPE,
        "requestId": payload.request_id,
        "subject": payload.subject,
        "requestedInfo": payload.requested_info,
        "recipient": payload.recipient or "",
        "context": payload.context,
        "status": "requested",
        "requestedAt": datetime.now(timezone.utc).isoformat(),
    }


async def _request_info_handler(job) -> dict[str, Any]:
    """Handle the `request-info-worker` Camunda job."""

    try:
        payload = _parse_payload(job)
        logger.log_debug(
            "Processing request-info job",
            request_id=payload.request_id or "unknown",
            subject=payload.subject,
            recipient=payload.recipient or "n/a",
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

    worker_name = os.getenv("CAMUNDA_WORKER_NAME", "request-info-worker")
    fetch_vars = ["requestedInfo", "message", "details", "requestId", "subject", "recipient"]

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
