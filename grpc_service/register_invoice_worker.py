"""Camunda 8 job worker for registering invoices.

The worker listens to the job type `register-invoice`, validates the incoming
variables, stores a new invoice in the database, and returns process variables
for Camunda on success.

Business problems are translated into Zeebe error states so they can be handled
in the Camunda Modeler. Technical problems are translated into job failures so
the engine can retry the job.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Mapping

from camunda_orchestration_sdk.runtime.job_worker import JobError, JobFailure, JobContext
from sqlalchemy.exc import SQLAlchemyError

from config.database import Base, SessionLocal, engine
from grpc_service.models import Invoice
from grpc_service.zeebe_config import create_job_worker
from utils import StructuredLogger, create_invoice


logger = StructuredLogger.for_module(__name__)

JOB_TYPE = "register-invoice"


# Ensure the invoice table exists before the worker processes jobs.
Base.metadata.create_all(bind=engine, tables=[Invoice.__table__])


class RegisterInvoiceError(Exception):
    """Base exception for register-invoice business and technical errors."""

    error_code = "REGISTER_INVOICE_ERROR"


class RegisterInvoiceValidationError(RegisterInvoiceError):
    """Raised when the incoming job payload is incomplete or invalid."""

    error_code = "REGISTER_INVOICE_VALIDATION_ERROR"


class RegisterInvoiceAlreadyExistsError(RegisterInvoiceError):
    """Raised when the invoice already exists in the database."""

    error_code = "REGISTER_INVOICE_ALREADY_EXISTS"


class RegisterInvoiceTechnicalError(RegisterInvoiceError):
    """Raised for database and infrastructure failures."""

    error_code = "REGISTER_INVOICE_TECHNICAL_ERROR"


@dataclass(frozen=True)
class RegisterInvoicePayload:
    """Validated payload extracted from a Camunda job."""

    amount: float
    invoice_id: str
    vendor: str


def _get_job_variables(job: JobContext) -> Mapping[str, Any]:
    """Return job variables as a mapping (converted from SDK model objects)."""
    variables = getattr(job, "variables", {})
    # SDK model objects expose `to_dict()`
    if hasattr(variables, "to_dict"):
        return variables.to_dict()
    if isinstance(variables, Mapping):
        return variables
    return {}


def _parse_payload(job: JobContext) -> RegisterInvoicePayload:
    """Validate and normalize the variables expected by the worker."""
    variables = _get_job_variables(job)

    raw_amount = variables.get("amount")
    raw_invoice_id = variables.get("invoiceID")
    raw_vendor = variables.get("vendor")

    if raw_amount is None or raw_invoice_id is None or raw_vendor is None:
        raise RegisterInvoiceValidationError(
            "Pflichtvariablen amount, invoiceID und vendor fehlen"
        )

    try:
        amount = float(raw_amount)
    except (TypeError, ValueError) as exc:
        raise RegisterInvoiceValidationError("amount muss eine Zahl sein") from exc

    invoice_id = str(raw_invoice_id).strip()
    vendor = str(raw_vendor).strip()

    if not invoice_id:
        raise RegisterInvoiceValidationError("invoiceID darf nicht leer sein")

    if not vendor:
        raise RegisterInvoiceValidationError("vendor darf nicht leer sein")

    if amount <= 0:
        raise RegisterInvoiceValidationError("amount muss größer als 0 sein")

    return RegisterInvoicePayload(amount=amount, invoice_id=invoice_id, vendor=vendor)


def _store_invoice(payload: RegisterInvoicePayload):
    """Persist a new invoice and map duplicate/technical errors to worker errors."""
    db = SessionLocal()
    try:
        invoice = create_invoice(db, payload.invoice_id, payload.vendor, payload.amount)
        if not invoice:
            raise RegisterInvoiceAlreadyExistsError(
                f"Rechnung {payload.invoice_id} existiert bereits"
            )

        logger.log_db_operation(
            "CREATE",
            "invoice",
            status="SUCCESS",
            invoice_id=invoice.id,
            supplier=invoice.supplier,
            amount=invoice.amount,
            source="camunda-job-worker",
        )

        return invoice
    except SQLAlchemyError as exc:
        db.rollback()
        logger.log_error(
            "Failed to store invoice for Camunda job",
            exc_info=exc,
            invoice_id=payload.invoice_id,
        )
        raise RegisterInvoiceTechnicalError(
            "Datenbankfehler beim Speichern der Rechnung"
        ) from exc
    finally:
        db.close()


def _invoice_to_variables(invoice) -> dict[str, Any]:
    """Convert the stored invoice into a Camunda-friendly variable payload."""
    return {
        "success": True,
        "message": "Invoice registered successfully",
        "invoiceId": invoice.id,
        "vendor": invoice.supplier,
        "amount": invoice.amount,
        "status": invoice.status,
        "createdAt": invoice.created_at.isoformat() if invoice.created_at else "",
        "updatedAt": invoice.updated_at.isoformat() if invoice.updated_at else "",
    }


def _map_and_raise_job_exception(exception: Exception, job: JobContext) -> None:
    """Map internal exceptions to SDK JobError/JobFailure and raise them."""
    variables = _get_job_variables(job)
    invoice_id = str(variables.get("invoiceID", "unknown"))

    if isinstance(exception, RegisterInvoiceError) and not isinstance(
        exception, RegisterInvoiceTechnicalError
    ):
        logger.log_warning(
            "Register invoice rejected",
            invoice_id=invoice_id,
            error_code=exception.error_code,
            reason=str(exception),
        )
        raise JobError(exception.error_code, str(exception))

    logger.log_error(
        "Register invoice failed technically",
        exc_info=exception,
        invoice_id=invoice_id,
    )
    # Fail the job so the engine can retry. Leave `retries=None` so the
    # worker will decrement retries by 1.
    raise JobFailure("Technischer Fehler beim Speichern der Rechnung", retries=None)


async def _register_invoice_handler(job: JobContext) -> dict[str, Any]:
    """Handle the `register-invoice` Camunda job.

    The handler returns a dict of variables on success. On business errors
    it raises `JobError`; on technical errors it raises `JobFailure` so the
    engine will retry the job.
    """
    try:
        payload = _parse_payload(job)
        logger.log_debug(
            "Processing register-invoice job",
            invoice_id=payload.invoice_id,
            amount=payload.amount,
            vendor=payload.vendor,
        )

        invoice = _store_invoice(payload)
        logger.log_debug(
            "Register-invoice job completed",
            invoice_id=invoice.id,
            status=invoice.status,
        )
        return _invoice_to_variables(invoice)

    except Exception as exc:
        _map_and_raise_job_exception(exc, job)


def create_worker():
    """Create and configure the Camunda worker instance.
    
    Automatically detects SaaS or self-hosted mode based on environment variables:
    
    For SaaS (Camunda Cloud):
        - CAMUNDA_CLIENT_MODE=saas
        - CAMUNDA_CLIENT_AUTH_CLIENT_ID
        - CAMUNDA_CLIENT_AUTH_CLIENT_SECRET
        - CAMUNDA_CLIENT_CLOUD_CLUSTER_ID
        - CAMUNDA_CLIENT_CLOUD_REGION
    
    For self-hosted:
        - ZEEBE_GRPC_ADDRESS (defaults to localhost:26500)
    """
    worker_name = os.getenv("CAMUNDA_WORKER_NAME", "register-invoice-worker")
    fetch_vars = ["amount", "invoiceID", "vendor"]
    worker = create_job_worker(
        job_type=JOB_TYPE,
        task_handler=_register_invoice_handler,
        timeout_ms=int(os.getenv("CAMUNDA_WORKER_TIMEOUT", "20000")),
        fetch_variables=fetch_vars,
        worker_name=worker_name,
    )

    return worker


async def run_worker() -> None:
    """Start the worker loop and keep polling for register-invoice jobs.
    
    Configuration:
        - For SaaS: Set CAMUNDA_CLIENT_MODE=saas + auth credentials
        - For self-hosted: Set ZEEBE_GRPC_ADDRESS (defaults to localhost:26500)
    """
    worker = create_worker()

    # Log startup info (informational only)
    if os.getenv("CAMUNDA_CLIENT_MODE", "").lower() == "saas":
        cluster_id = os.getenv("CAMUNDA_CLIENT_CLOUD_CLUSTER_ID", "unknown")
        region = os.getenv("CAMUNDA_CLIENT_CLOUD_REGION", "unknown")
        zeebe_address = f"{cluster_id}.{region}.zeebe.camunda.io:443"
    else:
        zeebe_address = os.getenv("ZEEBE_GRPC_ADDRESS", "localhost:26500")

    logger.log_debug(
        "Starting Camunda worker",
        task_type=JOB_TYPE,
        zeebe_address=zeebe_address,
        worker_name=worker.config.worker_name,
    )

    # Start background polling and keep the process running
    worker.start()
    await asyncio.Event().wait()


def main() -> None:
    """Entrypoint for `python -m grpc_service.register_invoice_worker`."""
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()