"""Mailpit listener that polls for emails, extracts PDFs, and starts a Camunda process."""

import asyncio
import base64
import os
import httpx
from pdf2image import convert_from_bytes
import io

from utils import StructuredLogger
from workers.runtime import publish_camunda_message

logger = StructuredLogger.for_module(__name__)

MAILPIT_API_URL = os.getenv("MAILPIT_API_URL", "http://mailpit:8025/api/v1")
NGROK_API_URL = os.getenv("NGROK_API_URL", "http://ngrok:4040/api/tunnels")
START_MESSAGE_NAME = "Message_InvoiceReceived"
N8N_WEBHOOK_ENDPOINT = "/webhook/extract-invoice"
LOCAL_PDF_PATH = "/app/shared_invoices"  # Pfad, wo die PDFs gespeichert werden


def get_pdf_first_page_as_base64(pdf_bytes: bytes) -> str:
    """Macht aus der ersten Seite der PDF ein Bild und gibt es als Base64 zurück."""
    try:
        # Wandelt nur die erste Seite der PDF in ein Bild um
        images = convert_from_bytes(pdf_bytes, first_page=1, last_page=1)
        if not images:
            return ""

        first_page = images[0]

        # Bild in den Arbeitsspeicher speichern (als PNG)
        img_buffer = io.BytesIO()
        first_page.save(img_buffer, format="PNG")

        # Als Base64-String codieren
        return base64.b64encode(img_buffer.getvalue()).decode("utf-8")
    except Exception as exc:
        logger.log_error("Fehler bei der PDF-zu-Bild Konvertierung", exc_info=exc)
        return ""


async def get_dynamic_ngrok_url() -> str:
    """Holt die aktuell aktive ngrok URL aus dem Container (Torwächter)."""
    logger.log_info("Warte auf ngrok URL...")
    async with httpx.AsyncClient(timeout=5.0) as client:
        for _ in range(15):  # Wartet bis zu 15 Sekunden auf ngrok
            try:
                resp = await client.get(NGROK_API_URL)
                tunnels = resp.json().get("tunnels", [])
                if tunnels:
                    url = tunnels[0]["public_url"]
                    logger.log_info(f"ngrok URL gefunden: {url}")
                    return url
            except Exception:
                pass
            await asyncio.sleep(1)

    logger.log_error("Konnte ngrok URL nicht abrufen.")
    return ""


async def poll_mailpit():
    """Polls Mailpit for new emails, extracts PDFs, and publishes Camunda messages."""

    logger.log_info("Starting Mailpit listener loop...")

    public_url = await get_dynamic_ngrok_url()
    if not public_url:
        logger.log_error("Skript gestoppt: Keine öffentliche ngrok-URL verfügbar.")
        return

    n8n_webhook_url = f"{public_url}{N8N_WEBHOOK_ENDPOINT}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            try:
                response = await client.get(f"{MAILPIT_API_URL}/messages")

                if response.status_code == 200:
                    data = response.json()

                    for msg in data.get("messages", []):
                        msg_id = msg["ID"]

                        details_resp = await client.get(
                            f"{MAILPIT_API_URL}/message/{msg_id}"
                        )
                        msg_details = details_resp.json()

                        for attachment in msg_details.get("Attachments", []):
                            if attachment.get("ContentType") == "application/pdf":
                                part_id = attachment["PartID"]

                                attach_resp = await client.get(
                                    f"{MAILPIT_API_URL}/message/{msg_id}/part/{part_id}"
                                )
                                pdf_bytes = attach_resp.content
                                base64_encoded = base64.b64encode(pdf_bytes).decode(
                                    "utf-8"
                                )

                                image_base64 = get_pdf_first_page_as_base64(pdf_bytes)

                                await publish_camunda_message(
                                    name=START_MESSAGE_NAME,
                                    correlation_key=msg_id,
                                    variables={
                                        "invoice_pdf_base64": base64_encoded,
                                        "n8n_dynamic_webhook_url": n8n_webhook_url,
                                        "invoice_image_base64": image_base64,
                                    },
                                    logger=logger,
                                    time_to_live=60_000,
                                )

                                logger.log_info(
                                    "[SUCCESS] Camunda Prozess gestartet.",
                                    webhook=n8n_webhook_url,
                                )

                        # E-Mail aus Mailpit löschen
                        await client.request(
                            "DELETE",
                            f"{MAILPIT_API_URL}/messages",
                            json={"IDs": [msg_id]},
                        )

            except Exception as exc:
                logger.log_error("Fehler im Mailpit-Listener-Zyklus", exc_info=exc)

            await asyncio.sleep(5)


def main() -> None:
    """Starts the Mailpit listener."""
    asyncio.run(poll_mailpit())


if __name__ == "__main__":
    main()
