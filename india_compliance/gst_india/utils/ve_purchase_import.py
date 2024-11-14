import frappe
from erpnext.accounts.doctype.chart_of_accounts_importer.chart_of_accounts_importer import (
    get_file,
)
from erpnext.accounts.doctype.chart_of_accounts_importer.chart_of_accounts_importer import (
    generate_data_from_excel,
)
from frappe.utils import flt
import json


ACCOUNT_HEAD_MAPPING = {"cgst": "Input Tax CGST - VE", "sgst": "Input Tax SGST - VE"}

TAXES = ("cgst", "sgst")


def import_invoices():
    file_name = (
        "/private/files/GRN_Data_20129252_11Nov2024_6386692536032502691bd15e.xlsx"
    )
    file_doc, extension = get_file(file_name)

    data = generate_data_from_excel(file_doc, extension, as_dict=True)

    invoices = get_invoice_wise_data(data)

    for inv, data in invoices.items():
        print(inv, "import")
        if frappe.db.exists("Purchase Invoice", inv):
            continue

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
    tax_account_wise_data = frappe._dict()
    items = data.get("items")

    for row in items:
        item_code = row.item_code
        for tax_type in TAXES:
            amount = row.get(tax_type)
            account_head = ACCOUNT_HEAD_MAPPING.get(tax_type)

            tax_account_wise_data.setdefault(
                account_head,
                {
                    "charge_type": "Actual",
                    "description": tax_type.upper(),
                    "cost_center": "Main - VE",
                    "included_in_print_rate": 0,
                    "dont_recompute_tax": 1,
                    "tax_amount": 0,
                    "item_wise_tax_detail": {},
                },
            )

            tax_account_wise_data[account_head]["tax_amount"] += flt(amount, 2)
            tax_account_wise_data[account_head]["item_wise_tax_detail"].setdefault(
                item_code, [row.gst_rate, 0]
            )
            tax_account_wise_data[account_head]["item_wise_tax_detail"][item_code][
                1
            ] += flt(amount)

    taxes = []
    for account, tax_row in tax_account_wise_data.items():
        row = {"account_head": account, **tax_row}
        row["item_wise_tax_detail"] = json.dumps(row.get("item_wise_tax_detail", {}))
        taxes.append(row)

    doc.update({"taxes": taxes})


def get_invoice_wise_data(data):
    invoices = frappe._dict()
    hsn_codes = {}
    for row in data:
        row = frappe._dict(row)
        inv = invoices.setdefault(
            row.document_no,
            frappe._dict(
                {
                    "date": row.supplier_invoice_date,
                    "naming_series": "GRN/.######.",
                    "name": row.document_no,
                    "bill_no": row.gst_inv_no,
                    "items": [],
                }
            ),
        )

        item = frappe._dict(
            {
                "item_code": row.product_code,
                "description": row.description,
                "gst_hsn_code": row.hsn_no,
                "qty": row.get("quantity(packs)"),
                "uom": "Nos",
                "rate": row.product_price / row.get("quantity(packs)"),
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

    diff = doc.grand_total - total

    if diff:
        doc.append(
            "taxes",
            {
                "account_head": "Rounded Off - VE",
                "charge_type": "Actual",
                "description": "Rounded Off",
                "cost_center": "Main - VE",
                "included_in_print_rate": 0,
                "dont_recompute_tax": 1,
                "tax_amount": diff,
            },
        )

    doc.save()
    doc.submit()
