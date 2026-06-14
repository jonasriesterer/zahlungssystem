"""Skript zum automatischen Generieren und Senden einer PDF-Rechnung an Mailpit."""

import smtplib
import os
from email.message import EmailMessage

from create_invoice import create_invoice, get_mock_data


def send_invoice():
    """Erstellt automatisch eine Rechnung und sendet sie an Mailpit."""

    # Temporärer Dateiname für den lokalen Ordner
    pdf_filename = "rechnung.pdf"

    print("Generiere neue Rechnung...")

    # 1. Test-Daten aus dem anderen Skript holen
    invoice_data = get_mock_data()

    # 2. PDF generieren lassen
    create_invoice(pdf_filename, invoice_data)
    print(f"Rechnung '{pdf_filename}' wurde erfolgreich gerendert.")

    # 3. E-Mail vorbereiten
    msg = EmailMessage()
    msg["Subject"] = f"Neue Rechnung {invoice_data['invoice_number']} zur Freigabe"

    # E-Mail Absender direkt aus den PDF-Daten übernehmen
    msg["From"] = invoice_data["sender_email"]
    msg["To"] = "rechnungseingang@eure-firma.de"

    body_text = (
        f"Hallo,\n\n"
        f"anbei finden Sie unsere aktuelle Rechnung {invoice_data['invoice_number']}.\n\n"
        f"Bitte überprüfen Sie diese und geben Sie sie zur Zahlung frei.\n\n"
        f"Mit freundlichen Grüßen\n"
        f"{invoice_data['sender_name']}"
    )
    msg.set_content(body_text)

    # 4. Die eben generierte PDF einlesen und anhängen
    try:
        with open(pdf_filename, "rb") as f:
            pdf_data = f.read()

        msg.add_attachment(
            pdf_data, maintype="application", subtype="pdf", filename=pdf_filename
        )

        # 5. An den lokalen Mailpit-Container senden (Port 1025)
        print("Sende E-Mail an Mailpit (localhost:1025)...")
        with smtplib.SMTP("localhost", 1025) as server:
            server.send_message(msg)

        print(
            "[SUCCESS] Die Rechnung wurde an Mailpit übergeben!"
        )

    except Exception as e:
        print(f"Fehler beim Senden der Mail: {e}")

    finally:
        if os.path.exists(pdf_filename):
            os.remove(pdf_filename)


if __name__ == "__main__":
    send_invoice()
