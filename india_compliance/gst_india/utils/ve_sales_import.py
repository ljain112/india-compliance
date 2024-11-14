import frappe
from erpnext.accounts.doctype.chart_of_accounts_importer.chart_of_accounts_importer import (
    get_file,
)
from erpnext.accounts.doctype.chart_of_accounts_importer.chart_of_accounts_importer import (
    generate_data_from_excel,
)
from frappe.utils import flt
import json

from erpnext.accounts.party import _get_party_details


ACCOUNT_HEAD_MAPPING = {
    "cgst": "Output Tax CGST - VE",
    "sgst": "Output Tax SGST - VE",
    "scheme_discount": "Scheme Discount - VE",
    "cash_discount": "Cash Discount - VE",
}

TAXES = ("scheme_discount", "cash_discount", "cgst", "sgst")

DOCUMENT_TYPE_ORDER = {"Invoice": 0, "Free Invoice": 1, "Credit Note": 2}


def import_invoices():
    file_name = "/private/files/Data_20129252_O_20241105023010_7325_E_05Nov2024_638663943037325347.xlsx"
    file_doc, extension = get_file(file_name)

    data = generate_data_from_excel(file_doc, extension, as_dict=True)

    invoices = get_invoice_wise_data(data)
    for inv, data in invoices.items():
        print(inv, "import")

        if frappe.db.exists("Sales Invoice", data.name):
            continue
        
        try:
            doc = frappe.new_doc("Sales Invoice")
            doc.name = data.name
            doc.update(
                {
                    "posting_date": data.date,
                    "set_posting_time": 1,
                    "due_date": data.date,
                    "update_stock": 1,
                    "customer": data.customer,
                    "supplier_address": "Castrol India-Billing",
                    "is_return": 1 if data.document_type == "Credit Note" else 0,
                    "return_against": data.return_against,
                }
            )

            if doc.is_return:
                doc.update_outstanding_for_self = 0

            party_details = _get_party_details(
                doc.customer,
                ignore_permissions=doc.flags.ignore_permissions,
                doctype=doc.doctype,
                company=doc.company,
                posting_date=doc.get("posting_date"),
                fetch_payment_terms_template=False,
                party_address=doc.customer_address,
                company_address=doc.get("company_address"),
            )

            for field in [
                "customer_address",
                "company_address",
                "contact_person",
                "contact_mobile",
            ]:
                doc.set(field, party_details.get(field))

            doc.taxes = []

            update_items(doc, data)
            update_taxes(doc, data)

            doc.set_missing_values()

            doc.insert()
            doc.save()
            

            update_round_off(doc, data)
            frappe.db.commit()
            doc.submit()
        except Exception as e:
            print(e)


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
                "taxable_value": row.taxable_value,
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

            if doc.is_return:
                amount = amount * -1

            tax_account_wise_data[account_head]["tax_amount"] += amount
            tax_account_wise_data[account_head]["item_wise_tax_detail"].setdefault(
                item_code, [flt(row.gst_rate), 0]
            )
            tax_account_wise_data[account_head]["item_wise_tax_detail"][item_code][
                1
            ] += amount

    taxes = []
    for account, tax_row in tax_account_wise_data.items():
        row = {"account_head": account, **tax_row}
        row["item_wise_tax_detail"] = json.dumps(row.get("item_wise_tax_detail", {}))
        taxes.append(row)

    doc.update({"taxes": taxes})


def get_invoice_wise_data(data):
    invoices = frappe._dict()
    for row in data:
        row = frappe._dict(row)
        invoice_no = row.get("invoice_no.")
        inv = invoices.setdefault(
            (row.invoice_date, row.document_type, invoice_no),
            frappe._dict(
                {
                    "date": row.invoice_date,
                    "name": invoice_no,
                    "items": [],
                    "customer": row.customer_code,
                    "gstin": row.get("customer_gstn_no."),
                    "document_type": row.document_type,
                    "return_against": row.get("ref._invoice_no."),
                }
            ),
        )

        qty = row.get("product_volume") / row.get("pack_size")

        total_rate = (
            row.get("total_value_incl_vat/gst")
            - row.get("vat/gst")
            - row.get("mop_discount")
            - row.get("coupon_discount_value")
            - row.get("scheme_discount_value")
        )
        rate = total_rate / qty

        item = frappe._dict(
            {
                "item_code": row.product_code,
                "description": row.description,
                "gst_hsn_code": row.hsn_number,
                "qty": qty,
                "uom": "Nos",
                "rate": rate,
                "cgst": (
                    row.cgst_value * -1
                    if "document_type" == "Credit Note"
                    else row.cgst_value
                ),
                "sgst": (
                    row.sgst_value * -1
                    if "document_type" == "Credit Note"
                    else row.sgst_value
                ),
                "scheme_discount": row.get("scheme_discount_value")
                + row.get("coupon_discount_value"),
                "cash_discount": row.get("mop_discount"),
                "gst_rate": 9,
                "total": row.get("total_value_incl_vat/gst"),
                "taxable_value": row.get("total_value_incl_vat/gst")
                - row.get("vat/gst"),
            }
        )

        inv.get("items").append(item)

    sorted_invoices = sorted(
        invoices.items(),
        key=lambda x: (
            x[0][0],  # Sort by date (first element of the key tuple)
            {"Invoice": 0, "Free Invoice": 1, "Credit Note": 2}[
                x[0][1]
            ],  # Sort by document type
            x[0][2],
        ),  # Sort by invoice number
    )

    return {k: v for k, v in sorted_invoices}


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
