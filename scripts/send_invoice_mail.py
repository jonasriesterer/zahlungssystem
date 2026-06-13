"""Skript zum Senden einer PDF-Rechnung per E-Mail an den lokalen Mailpit-Server."""

import smtplib
import tkinter as tk
from tkinter import filedialog
from email.message import EmailMessage

def select_pdf_file():
    """Öffnet einen Datei-Explorer zur Auswahl einer PDF."""
    root = tk.Tk()
    root.withdraw()  # Versteckt das leere Hauptfenster von tkinter

    file_path = filedialog.askopenfilename(
        title="Bitte eine PDF-Rechnung für den Anhang auswählen",
        filetypes=[("PDF Dateien", "*.pdf")]
    )
    return file_path

def send_invoice():
    """Erstellt die Mail und sendet sie an den lokalen Mailpit-Server."""
    pdf_file_path = select_pdf_file()

    if not pdf_file_path:
        print("Vorgang abgebrochen: Keine Datei ausgewählt.")
        return

    msg = EmailMessage()
    msg['Subject'] = 'Neue Rechnung zur Freigabe'
    msg['From'] = 'lieferant@beispiel.de'
    msg['To'] = 'rechnungseingang@eure-firma.de'
    msg.set_content('Hallo, anbei finden Sie unsere aktuelle Rechnung. Bitte überprüfen Sie diese.')

    # PDF einlesen und anhängen
    try:
        with open(pdf_file_path, 'rb') as f:
            pdf_data = f.read()

        msg.add_attachment(
            pdf_data,
            maintype='application',
            subtype='pdf',
            filename=pdf_file_path.split("/")[-1] # Nutzt den echten Dateinamen
        )

        # An den lokalen Mailpit-Container senden (Port 1025)
        with smtplib.SMTP('localhost', 1025) as server:
            server.send_message(msg)

        print(f"Erfolg: '{pdf_file_path}' wurde erfolgreich an Mailpit gesendet!")

    except Exception as e:
        print(f"Fehler beim Senden der Mail: {e}")

if __name__ == "__main__":
    send_invoice()
