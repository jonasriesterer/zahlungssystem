import os
import random
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import cm


def get_mock_data():
    """Gibt zufällig generierte Test-Daten für die Rechnung zurück."""

    # Zufälliges Rechnungsdatum (irgendwann in den letzten 30 Tagen)
    heute = datetime.now()
    tage_zurueck = random.randint(0, 30)
    rechnungsdatum_obj = heute - timedelta(days=tage_zurueck)
    lieferdatum_obj = rechnungsdatum_obj - timedelta(days=random.randint(1, 5))

    # Artikel-Pool (Daraus wählt das Skript zufällig aus)
    produkt_pool = [
        {
            "art_nr": "B-3025-078",
            "name": "B-3025, Farbe Grün",
            "desc": "Premium Ausführung",
            "price": 47.00,
            "unit": "Stk.",
        },
        {
            "art_nr": "B-3025-050",
            "name": "B-3025, Farbe Rot",
            "desc": "Premium Ausführung",
            "price": 47.00,
            "unit": "Stk.",
        },
        {
            "art_nr": "B-0050-050",
            "name": "B-0050, Farbe Blau",
            "desc": "Standard Edition",
            "price": 36.00,
            "unit": "Stk.",
        },
        {
            "art_nr": "A-0086-007",
            "name": "A-0086, Antik Look",
            "desc": "Musterartikel",
            "price": 56.00,
            "unit": "Stk.",
        },
        {
            "art_nr": "C-1122-333",
            "name": "C-1122, Industrie-Kleber",
            "desc": "100ml Tube",
            "price": 12.50,
            "unit": "Tube",
        },
        {
            "art_nr": "S-9999-001",
            "name": "Wartungsset Basis",
            "desc": "Ersatzteile",
            "price": 125.00,
            "unit": "Set",
        },
        {
            "art_nr": "V-13kg",
            "name": "Versand und Verpackung",
            "desc": "Pauschale",
            "price": 11.99,
            "unit": "Stk.",
        },
    ]

    # Zufällige Anzahl an Artikeln (1 bis 5 Positionen)
    anzahl_positionen = random.randint(1, 5)
    ausgewaehlte_produkte = random.sample(produkt_pool, anzahl_positionen)

    items = []
    net_total = 0.0

    # Positionen berechnen
    for index, produkt in enumerate(ausgewaehlte_produkte):
        qty = float(random.randint(1, 5))
        total_price = qty * produkt["price"]
        net_total += total_price

        items.append(
            {
                "pos": index + 1,
                "art_nr": produkt["art_nr"],
                "name": produkt["name"],
                "desc": produkt["desc"],
                "qty": qty,
                "unit": produkt["unit"],
                "price": produkt["price"],
                "total": total_price,
            }
        )

    # Steuern und Brutto berechnen (Kaufmännisch gerundet)
    tax_rate = 19.00
    tax_amount = round(net_total * (tax_rate / 100), 2)
    gross_total = round(net_total + tax_amount, 2)

    bearbeiter_liste = [
        "Max Mustermann",
        "Erika Musterfrau",
        "Klaus Klein",
        "Julia Groß",
        "Dorothea Schäfer",
    ]

    return {
        # --- ABSENDER (Konstant) ---
        "sender_name": "TechSupply GmbH",
        "sender_street": "Industriestraße 42",
        "sender_city": "76131 Karlsruhe",
        "sender_phone": "+49 721 123456",
        "sender_email": "billing@techsupply.de",
        "sender_web": "www.techsupply.de",
        # --- EMPFÄNGER (Konstant) ---
        "recipient_name": "Habermann & Söhne",
        "recipient_street": "Schnurlos Str. 81",
        "recipient_city": "34131 Kassel",
        # --- RECHNUNGSDATEN (Zufällig generiert) ---
        "invoice_number": f"RE-{rechnungsdatum_obj.year}-{random.randint(1000, 9999)}",
        "invoice_date": rechnungsdatum_obj.strftime("%d.%m.%Y"),
        "order_number": f"AUF-{random.randint(1000, 9999)}",
        "delivery_date": lieferdatum_obj.strftime("%d.%m.%Y"),
        "customer_number": "KD-1068",
        "clerk": random.choice(bearbeiter_liste),
        # --- MATHEMATIK & POSITIONEN ---
        "items": items,
        "net_total": net_total,
        "tax_rate": tax_rate,
        "tax_amount": tax_amount,
        "gross_total": gross_total,
        "delivery_terms": "Postversand",
        "payment_terms": "10 Tage 5% Skonto, 30 Tage ohne Abzug",
    }


def create_invoice(pdf_path, invoice_data):
    """Generiert die PDF basierend auf dem Dictionary."""
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    story = []
    styles = getSampleStyleSheet()

    style_normal = styles["Normal"]
    style_normal.fontSize = 9
    style_normal.leading = 12

    style_bold = ParagraphStyle("Bold", parent=style_normal, fontName="Helvetica-Bold")
    style_small = ParagraphStyle("Small", parent=style_normal, fontSize=7, leading=9)
    style_title = ParagraphStyle(
        "Title",
        parent=styles["Heading1"],
        fontSize=18,
        leading=22,
        fontName="Helvetica-Bold",
        spaceAfter=15,
    )

    # 1. HEADER (Absender Logo/Name)
    story.append(
        Paragraph(
            f"<font size=24 color='#008080'><b>{invoice_data['sender_name']}</b></font>",
            style_normal,
        )
    )
    story.append(Spacer(1, 2 * cm))

    # 2. ADRESSBLOCK
    address_left = [
        Paragraph(
            f"{invoice_data['sender_name']} {invoice_data['sender_street']} | {invoice_data['sender_city']}",
            style_small,
        ),
        Spacer(1, 5),
        Paragraph(invoice_data["recipient_name"], style_normal),
        Paragraph(invoice_data["recipient_street"], style_normal),
        Paragraph(invoice_data["recipient_city"], style_normal),
    ]

    address_right = [
        Paragraph(invoice_data["sender_name"], style_bold),
        Paragraph(invoice_data["sender_street"], style_normal),
        Paragraph(invoice_data["sender_city"], style_normal),
        Paragraph(f"Fon: {invoice_data['sender_phone']}", style_normal),
        Spacer(1, 5),
        Paragraph(invoice_data["sender_email"], style_normal),
        Paragraph(invoice_data["sender_web"], style_normal),
    ]

    address_table = Table([[address_left, address_right]], colWidths=[10 * cm, 6 * cm])
    address_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(address_table)
    story.append(Spacer(1, 2 * cm))

    # 3. RECHNUNGSTITEL
    story.append(Paragraph("Rechnung", style_title))

    # 4. METADATEN-BLOCK
    meta_data = [
        [
            Paragraph("Rechnungs-Nr.:", style_normal),
            Paragraph(invoice_data["invoice_number"], style_normal),
            Paragraph("Rechnungsdatum:", style_normal),
            Paragraph(invoice_data["invoice_date"], style_normal),
        ],
        [
            Paragraph("Auftrags-Nr.:", style_normal),
            Paragraph(invoice_data["order_number"], style_normal),
            Paragraph("Lieferdatum:", style_normal),
            Paragraph(invoice_data["delivery_date"], style_normal),
        ],
        [
            Paragraph("Kunden-Nr.:", style_normal),
            Paragraph(invoice_data["customer_number"], style_normal),
            Paragraph("Bearbeiter:", style_normal),
            Paragraph(invoice_data["clerk"], style_normal),
        ],
    ]

    meta_table = Table(meta_data, colWidths=[3.5 * cm, 4 * cm, 3.5 * cm, 4 * cm])
    meta_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(meta_table)
    story.append(Spacer(1, 1.5 * cm))

    # 5. RECHNUNGSPOSITIONEN
    table_data = [
        [
            Paragraph("Pos.", style_bold),
            Paragraph("Art.-Nr.", style_bold),
            Paragraph("Bezeichnung", style_bold),
            Paragraph("Menge", style_bold),
            Paragraph("Einheit", style_bold),
            Paragraph("E-Preis €", style_bold),
            Paragraph("Gesamt €", style_bold),
        ]
    ]

    for item in invoice_data["items"]:
        desc_paragraph = Paragraph(
            f"<b>{item['name']}</b><br/><font size=7>{item['desc']}</font>",
            style_normal,
        )
        table_data.append(
            [
                Paragraph(str(item["pos"]), style_normal),
                Paragraph(item["art_nr"], style_normal),
                desc_paragraph,
                Paragraph(f"{item['qty']:.2f}".replace(".", ","), style_normal),
                Paragraph(item["unit"], style_normal),
                Paragraph(f"{item['price']:.2f}".replace(".", ","), style_normal),
                Paragraph(f"{item['total']:.2f}".replace(".", ","), style_normal),
            ]
        )

    items_table = Table(
        table_data,
        colWidths=[1 * cm, 2.5 * cm, 6.5 * cm, 1.5 * cm, 1.5 * cm, 2 * cm, 2 * cm],
    )
    items_table.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 0), (-1, 0), 1.5, colors.black),
                ("LINEBELOW", (0, 0), (-1, 0), 1, colors.black),
                ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(items_table)
    story.append(Spacer(1, 1 * cm))

    # 6. SUMMEN-BLOCK
    totals_data = [
        [
            Paragraph("Summe Netto", style_normal),
            Paragraph("€", style_normal),
            Paragraph(
                f"{invoice_data['net_total']:.2f}".replace(".", ","), style_normal
            ),
        ],
        [
            Paragraph(
                f"{invoice_data['tax_rate']}% USt. auf {invoice_data['net_total']:.2f}".replace(
                    ".", ","
                ),
                style_normal,
            ),
            Paragraph("€", style_normal),
            Paragraph(
                f"{invoice_data['tax_amount']:.2f}".replace(".", ","), style_normal
            ),
        ],
        [
            Paragraph("Endsumme", style_bold),
            Paragraph("€", style_bold),
            Paragraph(
                f"{invoice_data['gross_total']:.2f}".replace(".", ","), style_bold
            ),
        ],
    ]

    totals_table = Table(totals_data, colWidths=[6.5 * cm, 0.5 * cm, 2 * cm])
    totals_table.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 0), (-1, 0), 1, colors.black),
                ("LINEABOVE", (0, -1), (-1, -1), 1.5, colors.black),
                ("LINEBELOW", (0, -1), (-1, -1), 1.5, colors.black),
                ("ALIGN", (2, 0), (2, -1), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )

    layout_table = Table([["", totals_table]], colWidths=[8 * cm, 9 * cm])
    story.append(layout_table)
    story.append(Spacer(1, 1.5 * cm))

    # 7. FOOTER
    story.append(
        Paragraph(f"Lieferbedingung: {invoice_data['delivery_terms']}", style_normal)
    )
    story.append(Paragraph(invoice_data["payment_terms"], style_normal))

    doc.build(story)


if __name__ == "__main__":
    data = get_mock_data()

    # Damit du die PDFs lokal unterscheiden kannst, nehmen wir die Rechnungsnummer in den Dateinamen auf
    filename = f"rechnung_{data['invoice_number']}.pdf"
    create_invoice(filename, data)
    print(f"PDF '{filename}' wurde erfolgreich erstellt!")
