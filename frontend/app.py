import os
import sys
from flask import Flask, render_template, request, flash, redirect, url_for

# Fügt das Hauptverzeichnis zum Pfad hinzu, damit wir euren test_client importieren können
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from client.test_client import InvoiceClient

app = Flask(__name__)
app.secret_key = "super_secret_hochschul_key" # Wird für die Flash-Messages benötigt

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # Daten aus dem Formular auslesen
        invoice_id = request.form.get('invoice_id')
        supplier = request.form.get('supplier')
        try:
            amount = float(request.form.get('amount', 0.0))
        except ValueError:
            flash('Bitte einen gültigen Betrag eingeben.', 'error')
            return redirect(url_for('index'))

        # Verbindung zum gRPC Backend herstellen
        try:
            # Falls ihr das Frontend in Docker laufen lasst, müsst ihr 'grpc-server' verwenden, 
            # lokal reicht 'localhost'
            grpc_host = os.getenv('GRPC_HOST', 'localhost')
            client = InvoiceClient(host=grpc_host, port=50051)
            
            # gRPC Call: CreateInvoice
            invoice = client.create_invoice(invoice_id, supplier, amount)
            
            if invoice:
                flash(f'Erfolg: Rechnung {invoice_id} wurde gespeichert!', 'success')
            else:
                flash(f'Fehler: Rechnung {invoice_id} konnte nicht erstellt werden (existiert sie bereits?).', 'error')
                
        except Exception as e:
            flash(f'Systemfehler: Keine Verbindung zum Backend ({str(e)})', 'error')
        finally:
            # Verbindung schließen, falls erforderlich (client.close() ist im test_client vorhanden)
            try:
                client.close()
            except Exception:
                pass

        return redirect(url_for('index'))
        
    return render_template('index.html')

if __name__ == '__main__':
    # Startet den Server lokal auf Port 5000
    app.run(host='0.0.0.0', port=5000, debug=True)