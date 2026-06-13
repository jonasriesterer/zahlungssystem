"""Camunda 8 Cloud worker for registering invoices."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from config.database import Base, SessionLocal, engine
from grpc_service.models import Invoice
from utils import StructuredLogger, create_invoice
from workers.errors import (
    CamundaJobBusinessError,
    CamundaJobTechnicalError,
    CamundaJobValidationError,
)
from workers.job_types import REGISTER_INVOICE_JOB_TYPE
from workers.runtime import create_job_worker, get_job_variables, map_job_exception, run_worker
from workers.helpers import _as_mapping


logger = StructuredLogger.for_module(__name__)


class RegisterInvoiceValidationError(CamundaJobValidationError):
    """Raised when the incoming job payload is incomplete or invalid."""

    error_code = "REGISTER_INVOICE_VALIDATION_ERROR"


class RegisterInvoiceAlreadyExistsError(CamundaJobBusinessError):
    """Raised when the invoice already exists in the database."""

    error_code = "REGISTER_INVOICE_ALREADY_EXISTS"


class RegisterInvoiceTechnicalError(CamundaJobTechnicalError):
    """Raised for database and infrastructure failures."""

    error_code = "REGISTER_INVOICE_TECHNICAL_ERROR"


@dataclass(frozen=True)
class RegisterInvoicePayload:
    """Validated payload extracted from a Camunda job."""

    amount: float
    invoice_id: str
    vendor: str


# Ensure the invoice table exists before the worker processes jobs.
Base.metadata.create_all(bind=engine, tables=[Invoice.__table__])


def _parse_payload(job) -> RegisterInvoicePayload:
    """Validate and normalize the variables expected by the worker."""

    variables = get_job_variables(job)

    invoice = _as_mapping(variables.get("invoice"))
    if not invoice:
        raise RegisterInvoiceValidationError("invoice-Objekt fehlt in den Job-Variablen")

    raw_amount = invoice.get("amount")
    raw_invoice_id = invoice.get("id")
    raw_vendor = invoice.get("vendor")

    if raw_amount is None or raw_invoice_id is None or raw_vendor is None:
        raise RegisterInvoiceValidationError(
            "Pflichtvariablen amount, id und vendor fehlen"
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


async def _register_invoice_handler(job) -> dict[str, Any]:
    """Handle the `register-invoice` Camunda job."""

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
        logger.log_info(
            "Register-invoice successfully processed",
            job_type=REGISTER_INVOICE_JOB_TYPE,
            invoice_id=invoice.id,
            status=invoice.status,
        )
        return _invoice_to_variables(invoice)
    except (
        RegisterInvoiceValidationError,
        RegisterInvoiceAlreadyExistsError,
        RegisterInvoiceTechnicalError,
    ) as exc:
        map_job_exception(
            exc,
            job,
            job_label="Register invoice job",
            technical_message="Technischer Fehler beim Speichern der Rechnung",
            logger=logger,
        )


def create_worker():
    """Create and configure the Camunda worker instance."""

    worker_name = REGISTER_INVOICE_JOB_TYPE + "-worker"
    fetch_vars = ["invoice"]

    return create_job_worker(
        job_type=REGISTER_INVOICE_JOB_TYPE,
        task_handler=_register_invoice_handler,
        timeout_ms=int(os.getenv("CAMUNDA_WORKER_TIMEOUT", "20000")),
        fetch_variables=fetch_vars,
        worker_name=worker_name,
    )


async def run_worker_instance() -> None:
    """Start the worker loop and keep polling for register-invoice jobs."""

    worker = create_worker()
    await run_worker(worker, job_type=REGISTER_INVOICE_JOB_TYPE, logger=logger)


def main() -> None:
    """Entrypoint for `python -m workers.register_invoice_worker`."""

    asyncio.run(run_worker_instance())


if __name__ == "__main__":
    main()
