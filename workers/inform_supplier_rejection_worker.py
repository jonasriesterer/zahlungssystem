"""Camunda 8 worker for informing suppliers about rejected invoices."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from camunda_orchestration_sdk.runtime.job_worker import JobContext

from utils import StructuredLogger
from workers.errors import CamundaJobValidationError
from workers.job_types import INFORM_SUPPLIER_REJECTION_JOB_TYPE
from workers.runtime import create_job_worker, get_job_variables, map_job_exception, run_worker


logger = StructuredLogger.for_module(__name__)

DEFAULT_REJECTION_MESSAGE = "Die Compliance-Richtlinien wurden nicht eingehalten."


class InformSupplierRejectionValidationError(CamundaJobValidationError):
    """Raised when the incoming inform-supplier-rejection payload is invalid."""

    error_code = "INFORM_SUPPLIER_REJECTION_VALIDATION_ERROR"


@dataclass(frozen=True)
class InformSupplierRejectionPayload:
    """Validated payload extracted from a Camunda job."""

    invoice_id: str
    store_id: str
    amount: float
    rejection_msg: str


def _parse_payload(job: JobContext) -> InformSupplierRejectionPayload:
    """Validate and normalize the variables expected by the worker."""

    variables = get_job_variables(job)

    raw_invoice_id = variables.get("invoiceID")
    raw_store_id = variables.get("storeId")
    raw_amount = variables.get("amount")
    raw_rejection_msg = variables.get("rejectionMsg")

    invoice_id = str(raw_invoice_id or "").strip()
    if not invoice_id:
        raise InformSupplierRejectionValidationError("invoiceID darf nicht leer sein")

    store_id = str(raw_store_id or "").strip()
    if not store_id:
        raise InformSupplierRejectionValidationError("storeId darf nicht leer sein")

    if raw_amount is None:
        raise InformSupplierRejectionValidationError("amount fehlt in den Job-Variablen")

    try:
        amount = float(raw_amount)
    except (TypeError, ValueError) as exc:
        raise InformSupplierRejectionValidationError("amount muss eine Zahl sein") from exc

    rejection_msg = str(raw_rejection_msg or "").strip() or DEFAULT_REJECTION_MESSAGE

    return InformSupplierRejectionPayload(
        invoice_id=invoice_id,
        store_id=store_id,
        amount=amount,
        rejection_msg=rejection_msg
    )


def _print_email_preview(payload: InformSupplierRejectionPayload) -> None:
    """Print a clean e-mail preview to the terminal."""

    recipient = f"lieferant-store-{payload.store_id}@uni-projekt.de"
    subject = f"Ablehnung Ihrer Rechnung {payload.invoice_id}"
    amount_text = f"{payload.amount:.2f} EUR"

    print()
    print("=" * 72)
    print("E-MAIL-VORSCHAU")
    print("=" * 72)
    print(f"An: {recipient}")
    print(f"Betreff: {subject}")
    print()
    print("Guten Tag,")
    print()
    print(
        f"leider müssen wir Ihnen mitteilen, dass die Rechnung {payload.invoice_id} "
        f"über {amount_text} abgelehnt wurde."
    )
    print(f"Rechnungsbetrag: {amount_text}")
    print(f"Invoice-ID: {payload.invoice_id}")
    print(f"complianceBemerkung: {payload.rejection_msg}")
    print()
    print("Bitte prüfen Sie die Angaben und kontaktieren Sie uns bei Rückfragen.")
    print()
    print("Mit freundlichen Grüßen")
    print("Ihr Rechnungsbearbeitungsteam")
    print("=" * 72)
    print()


async def _inform_supplier_rejection_handler(job: JobContext) -> dict[str, Any]:
    """Handle the `inform-supplier-rejection` Camunda job."""

    try:
        payload = _parse_payload(job)
        logger.log_debug(
            "Processing inform-supplier-rejection job",
            invoice_id=payload.invoice_id,
            amount=payload.amount,
        )

        _print_email_preview(payload)

        logger.log_debug(
            "Inform-supplier-rejection job completed",
            invoice_id=payload.invoice_id
        )
        logger.log_info(
            "Inform-supplier-rejection successfully processed",
            job_type=INFORM_SUPPLIER_REJECTION_JOB_TYPE,
            invoice_id=payload.invoice_id,
            store_id=payload.store_id,
        )
        return {"email_sent": True}
    except InformSupplierRejectionValidationError as exc:
        map_job_exception(
            exc,
            job,
            job_label="Inform supplier rejection job",
            technical_message="Technischer Fehler beim Informieren des Lieferanten",
            logger=logger,
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        map_job_exception(
            exc,
            job,
            job_label="Inform supplier rejection job",
            technical_message="Technischer Fehler beim Informieren des Lieferanten",
            logger=logger,
        )


def create_worker():
    """Create and configure the inform-supplier-rejection worker instance."""

    worker_name = INFORM_SUPPLIER_REJECTION_JOB_TYPE + "-worker"
    fetch_vars = ["invoiceID", "amount", "rejectionMsg", "storeId"]

    return create_job_worker(
        job_type=INFORM_SUPPLIER_REJECTION_JOB_TYPE,
        task_handler=_inform_supplier_rejection_handler,
        timeout_ms=int(os.getenv("CAMUNDA_WORKER_TIMEOUT", "20000")),
        fetch_variables=fetch_vars,
        worker_name=worker_name,
    )


async def run_worker_instance() -> None:
    """Start the worker loop and keep polling for inform-supplier-rejection jobs."""

    worker = create_worker()
    await run_worker(worker, job_type=INFORM_SUPPLIER_REJECTION_JOB_TYPE, logger=logger)


def main() -> None:
    """Entrypoint for `python -m workers.inform_supplier_rejection_worker`."""

    asyncio.run(run_worker_instance())


if __name__ == "__main__":
    main()