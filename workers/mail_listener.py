"""Mailpit listener that polls for emails, extracts PDFs, and starts a Camunda process."""

import asyncio
import base64
import os
import httpx

from utils import StructuredLogger
from workers.runtime import publish_camunda_message

logger = StructuredLogger.for_module(__name__)

MAILPIT_API_URL = os.getenv("MAILPIT_API_URL", "http://mailpit:8025/api/v1")
NGROK_API_URL = os.getenv("NGROK_API_URL", "http://ngrok:4040/api/tunnels")
START_MESSAGE_NAME = "Message_InvoiceReceived"
N8N_WEBHOOK_ENDPOINT = "/webhook-test/extract-invoice"


async def get_dynamic_ngrok_url(client: httpx.AsyncClient) -> str:
    """Holt die aktuell aktive, dynamische ngrok URL aus dem lokalen Container."""
    try:
        resp = await client.get(NGROK_API_URL)
        tunnels = resp.json().get("tunnels", [])
        if tunnels:
            return tunnels[0]["public_url"]
    except Exception as exc:
        logger.log_error("Konnte ngrok URL nicht abrufen", exc_info=exc)
    return ""


async def poll_mailpit():
    """Polls Mailpit for new emails, extracts PDFs, and publishes Camunda messages."""

    logger.log_info("Starting Mailpit listener loop...")

    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            try:
                response = await client.get(f"{MAILPIT_API_URL}/messages")

                if response.status_code == 200:
                    data = response.json()

                    for msg in data.get("messages", []):
                        msg_id = msg["ID"]

                        # Neue ngrok URL abfragen
                        public_url = await get_dynamic_ngrok_url(client)
                        # Hier bauen wir den kompletten Pfad zu deinem n8n Webhook:
                        n8n_webhook_url = f"{public_url}{N8N_WEBHOOK_ENDPOINT}"

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

                                # Hier übergeben wir jetzt ZWEI Variablen an Camunda!
                                await publish_camunda_message(
                                    name=START_MESSAGE_NAME,
                                    correlation_key=msg_id,
                                    variables={
                                        "invoice_pdf_base64": base64_encoded,
                                        "n8n_dynamic_webhook_url": n8n_webhook_url,
                                    },
                                    logger=logger,
                                    time_to_live=60_000,
                                )

                                logger.log_info(
                                    "Camunda Prozess gestartet.",
                                    webhook=n8n_webhook_url,
                                )

                        # Richtiges Delete (ohne json argument Fehler)
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
