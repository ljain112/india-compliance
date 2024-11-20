import frappe
from erpnext.accounts.doctype.chart_of_accounts_importer.chart_of_accounts_importer import (
    generate_data_from_excel,
    get_file,
)


def import_invoices():
    file_name = "/private/files/GRN_Data_20129252_19Nov2024_638676253696757531.xlsx"
    file_doc, extension = get_file(file_name)

    data = generate_data_from_excel(file_doc, extension, as_dict=True)

    invoices = get_invoice_wise_data(data)

    for inv, data in invoices.items():
        if frappe.db.exists("Purchase Invoice", inv):
            continue
        print(inv, "import")

        doc = frappe.new_doc("Purchase Invoice")
        doc.name = data.name
        doc.update(
            {
                "set_posting_time": 1,
                "posting_date": data.date,
                "bill_no": data.bill_no,
                "bill_date": data.date,
                "due_date": data.date,
                "update_stock": 1,
                "items": [],
                "supplier": "Castrol India",
                "supplier_address": "Castrol India-Billing",
                "billing_address": "Veer Enterprises-Billing",
            }
        )

        update_items(doc, data)
        update_taxes(doc, data)

        doc.insert()
        doc.save()

        update_round_off(doc, data)
        # doc.submit()


def update_items(doc, data):
    inv_items = data.get("items")
    items = []
    for row in inv_items:
        items.append(
            {
                "item_code": row.item_code,
                "description": row.description,
                "gst_hsn_code": row.gst_hsn_code,
                "qty": row.qty,
                "uom": row.uom,
                "rate": row.rate,
            }
        )

    doc.update({"items": items})


def update_taxes(doc, data):
    doc.taxes = []
    taxes = []
    taxes.append(
        {
            "add_deduct_tax": "Deduct",
            "charge_type": "On Net Total",
            "description": "Cash Discount",
            "cost_center": "Main - VE",
            "included_in_print_rate": 0,
            "rate": 1.5,
            "account_head": "Cash Discount Received - VE",
        },
    )

    taxes.append(
        {
            "charge_type": "On Previous Row Total",
            "description": "CGST",
            "cost_center": "Main - VE",
            "included_in_print_rate": 0,
            "rate": 9,
            "account_head": "Input Tax CGST - VE",
            "row_id": 1,
        },
    )

    taxes.append(
        {
            "charge_type": "On Previous Row Total",
            "description": "SGST",
            "cost_center": "Main - VE",
            "included_in_print_rate": 0,
            "rate": 9,
            "account_head": "Input Tax SGST - VE",
            "row_id": 1,
        },
    )

    taxes.append(
        {
            "add_deduct_tax": "Add",
            "charge_type": "Actual",
            "description": "TCS",
            "cost_center": "Main - VE",
            "included_in_print_rate": 0,
            "tax_amount": abs(data.tds_amount) if abs(data.tds_amount) > 1 else 0,
            "account_head": "TCS On Purchase AY 25-26 - VE",
        },
    )

    doc.update({"taxes": taxes})


def get_invoice_wise_data(data):
    invoices = frappe._dict()
    hsn_codes = {}
    for row in data:

        row = frappe._dict(row)
        if row.document_type == "Goods In Transit":
            continue
        inv = invoices.setdefault(
            row.document_no,
            frappe._dict(
                {
                    "date": row.supplier_invoice_date,
                    "naming_series": "GRN/.######.",
                    "name": row.document_no,
                    "bill_no": row.gst_inv_no,
                    "items": [],
                    "tds_amount": 0,
                    "total": 0,
                }
            ),
        )

        rate_after_cd = row.cgst_value * 100 / row.cgst_percentage
        original_rate = rate_after_cd / 0.985

        inv["tds_amount"] += rate_after_cd - row.product_price
        inv["total"] += row.product_price + row.cgst_value + row.sgst_value

        item = frappe._dict(
            {
                "item_code": row.product_code,
                "description": row.description,
                "gst_hsn_code": row.hsn_no,
                "qty": row.get("quantity(packs)"),
                "uom": "Nos",
                "rate": original_rate / row.get("quantity(packs)"),
                "cgst": row.cgst_value,
                "sgst": row.sgst_value,
                "gst_rate": row.cgst_percentage,
                "total": row.product_price + row.cgst_value + row.sgst_value,
            }
        )
        hsn_codes.setdefault(row.hsn_no, []).append(row.product_code)

        inv.get("items").append(item)

    for hsn, items in hsn_codes.items():
        frappe.db.set_value("Item", {"name": ["in", items]}, "gst_hsn_code", hsn)

    return frappe._dict(sorted(invoices.items()))


def update_round_off(doc, data):
    total = 0
    for row in data.get("items"):
        total += row.total

    diff = doc.grand_total - data.total
    print(diff)

    if -1 <= diff <= 1:
        doc.save()
        doc.submit()
    else:
        # Raise an error if the round off is greater than the allowed range
        print("Round off is greater than 1")
