"""Camunda 8 worker for executing payment orders via RabbitMQ."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import grpc
import pika
from camunda_orchestration_sdk.runtime.job_worker import JobContext, JobFailure

from grpc_service.generated import invoice_pb2, invoice_pb2_grpc
from utils import RabbitMQConnection, StructuredLogger
from workers.errors import CamundaJobBusinessError, CamundaJobTechnicalError, CamundaJobValidationError
from workers.job_types import EXECUTE_PAYMENT_JOB_TYPE
from workers.runtime import create_job_worker, get_job_variables, map_job_exception, run_worker


logger = StructuredLogger.for_module(__name__)

DEFAULT_PAYMENT_METHOD = "transfer"
DEFAULT_REQUESTED_BY = "camunda-worker/execute-payment"
DEFAULT_RABBITMQ_URL = (
    "amqp://guest:guest@rabbitmq:5672/%2F?heartbeat=300&blocked_connection_timeout=300"
)
DEFAULT_GRPC_TARGET = "grpc-server:50051"


class ExecutePaymentValidationError(CamundaJobValidationError):
    """Raised when the incoming execute-payment payload is invalid."""

    error_code = "EXECUTE_PAYMENT_VALIDATION_ERROR"


class ExecutePaymentBusinessError(CamundaJobBusinessError):
    """Raised when the referenced invoice cannot be processed."""

    error_code = "EXECUTE_PAYMENT_BUSINESS_ERROR"


class ExecutePaymentTechnicalError(CamundaJobTechnicalError):
    """Raised when RabbitMQ or gRPC infrastructure calls fail."""

    error_code = "EXECUTE_PAYMENT_TECHNICAL_ERROR"


@dataclass(frozen=True)
class ExecutePaymentPayload:
    """Validated payload extracted from a Camunda job."""

    invoice_id: str


def _parse_payload(job: JobContext) -> ExecutePaymentPayload:
    """Validate and normalize the variables expected by the worker."""

    variables = get_job_variables(job)
    invoice_id = str(variables.get("invoiceID") or "").strip()

    if not invoice_id:
        raise ExecutePaymentValidationError("invoiceID darf nicht leer sein")

    return ExecutePaymentPayload(invoice_id=invoice_id)


def _fetch_invoice(invoice_id: str) -> Any:
    """Load the invoice amount from the invoice gRPC service."""

    target = os.getenv("GRPC_SERVER_TARGET", DEFAULT_GRPC_TARGET)
    channel = grpc.insecure_channel(target)
    stub = invoice_pb2_grpc.InvoiceServiceStub(channel)

    try:
        request = getattr(invoice_pb2, "GetInvoiceRequest")(id=invoice_id)
        response = stub.GetInvoice(request, timeout=5)
        invoice = response.invoice
        if not getattr(invoice, "id", ""):
            raise ExecutePaymentBusinessError(f"Rechnung {invoice_id} konnte nicht gefunden werden")
        return invoice
    except grpc.RpcError as exc:
        code = getattr(exc, "code", lambda: None)()
        details = getattr(exc, "details", lambda: "")()
        if str(code).endswith("NOT_FOUND"):
            raise ExecutePaymentBusinessError(f"Rechnung {invoice_id} konnte nicht gefunden werden") from exc
        raise ExecutePaymentTechnicalError(
            f"gRPC-Zugriff auf Rechnung {invoice_id} fehlgeschlagen: {details or exc}"
        ) from exc
    finally:
        channel.close()


def _build_payment_order(invoice: Any, requested_by: str) -> dict[str, Any]:
    """Build the RabbitMQ payload for the payment service."""

    payment_id = str(uuid.uuid4())
    amount = float(getattr(invoice, "amount", 0.0) or 0.0)

    return {
        "id": payment_id,
        "invoice_id": str(getattr(invoice, "id", "")).strip(),
        "amount": amount,
        "payment_method": DEFAULT_PAYMENT_METHOD,
        "timestamp": int(datetime.now().timestamp()),
        "status": "pending",
        "requested_by": requested_by,
    }


def _publish_payment_order(payload: dict[str, Any]) -> None:
    """Publish the payment order to RabbitMQ."""

    rmq = RabbitMQConnection(rabbitmq_url=os.getenv("RABBITMQ_URL", DEFAULT_RABBITMQ_URL))
    try:
        rmq.connect(max_retries=5, retry_delay=2)
        rmq.declare_queue("payment_orders", durable=True)
        rmq.publish_message("payment_orders", json.dumps(payload), persistent=True)
    except Exception as exc:
        logger.log_error(
            "Failed to publish payment order",
            exc_info=exc,
            invoice_id=payload.get("invoice_id"),
            payment_id=payload.get("id"),
        )
        raise ExecutePaymentTechnicalError(
            "Zahlungsauftrag konnte nicht an RabbitMQ gesendet werden"
        ) from exc
    finally:
        connection = getattr(rmq, "connection", None)
        if connection and not connection.is_closed:
            try:
                connection.close()
            except (pika.exceptions.AMQPError, RuntimeError, OSError):
                pass


async def _execute_payment_handler(job: JobContext) -> dict[str, Any]:
    """Handle the `execute-payment` Camunda job."""

    try:
        payload = _parse_payload(job)
        logger.log_debug("Processing execute-payment job", invoice_id=payload.invoice_id)

        invoice = _fetch_invoice(payload.invoice_id)
        payment_order = _build_payment_order(invoice, DEFAULT_REQUESTED_BY)
        _publish_payment_order(payment_order)

        logger.log_debug(
            "Execute-payment job completed",
            invoice_id=payload.invoice_id,
            payment_id=payment_order["id"],
        )
        logger.log_info(
            "Execute-payment successfully processed",
            job_type=EXECUTE_PAYMENT_JOB_TYPE,
            invoice_id=payload.invoice_id,
            payment_id=payment_order["id"],
            queue="payment_orders",
        )
        return {
            "payment_order_created": True,
            "payment_id": payment_order["id"],
            "invoiceID": payload.invoice_id,
            "queue": "payment_orders",
        }
    except (ExecutePaymentValidationError, ExecutePaymentBusinessError) as exc:
        map_job_exception(
            exc,
            job,
            job_label="Execute payment job",
            technical_message="Technischer Fehler beim Erstellen des Zahlungsauftrags",
            logger=logger,
        )
    except ExecutePaymentTechnicalError as exc:
        logger.log_error(
            "Execute payment job failed technically",
            exc_info=exc,
            invoice_id=str(get_job_variables(job).get("invoiceID") or "unknown"),
        )
        raise JobFailure(
            "Technischer Fehler beim Erstellen des Zahlungsauftrags",
            retries=3,
        ) from exc


def create_worker():
    """Create and configure the execute-payment worker instance."""

    worker_name = EXECUTE_PAYMENT_JOB_TYPE + "-worker"
    fetch_vars = ["invoiceID"]

    return create_job_worker(
        job_type=EXECUTE_PAYMENT_JOB_TYPE,
        task_handler=_execute_payment_handler,
        timeout_ms=int(os.getenv("CAMUNDA_WORKER_TIMEOUT", "20000")),
        fetch_variables=fetch_vars,
        worker_name=worker_name,
    )


async def run_worker_instance() -> None:
    """Start the worker loop and keep polling for execute-payment jobs."""

    worker = create_worker()
    await run_worker(worker, job_type=EXECUTE_PAYMENT_JOB_TYPE, logger=logger)


def main() -> None:
    """Entrypoint for `python -m workers.execute_payment_worker`."""

    asyncio.run(run_worker_instance())


if __name__ == "__main__":
    main()