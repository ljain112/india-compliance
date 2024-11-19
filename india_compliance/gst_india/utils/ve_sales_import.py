import frappe
from erpnext.accounts.doctype.chart_of_accounts_importer.chart_of_accounts_importer import (
    generate_data_from_excel,
    get_file,
)
from erpnext.accounts.party import _get_party_details
from erpnext.controllers.sales_and_purchase_return import get_ref_item_dict

DOCUMENT_TYPE_ORDER = {"Invoice": 0, "Free Invoice": 1, "Credit Note": 2}


def import_invoices():
    file_name = "/private/files/Data_20129252_O_20241105023010_7325_E_05Nov2024_638663943037325347.xlsx"
    file_doc, extension = get_file(file_name)

    data = generate_data_from_excel(file_doc, extension, as_dict=True)

    invoices = get_invoice_wise_data(data)
    for inv, data in invoices.items():

        try:
            if frappe.db.exists("Sales Invoice", data.name):
                continue

            print("Importing", inv)

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
                    "is_return": data.is_return,
                    "return_against": data.return_against,
                }
            )

            if doc.is_return:
                doc.update_outstanding_for_self = 0
                doc.update_billed_amount_in_sales_order = 0
                doc.update_billed_amount_in_delivery_note = 0

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

            update_gst_in_address(data, party_details.customer_address)

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
            if doc.is_return:
                update_item_rate(doc)

            doc.set_missing_values()

            doc.insert()
            doc.save()

            update_round_off(doc, data)
        except Exception as e:
            print(e)


def update_gst_in_address(data, address_name):
    if data.gstin != frappe.db.get_value("Address", address_name, "gstin"):
        print("Updated Party GSTIN")
        frappe.db.set_value(
            "Address", address_name, "gstin", data.gstin, update_modified=True
        )


def update_item_rate(doc):
    if not doc.is_return or not doc.return_against:
        return

    select_fields = "item_code, qty, stock_qty, rate, parenttype, conversion_factor"
    valid_items = frappe._dict()

    for d in frappe.db.sql(
        f"""select {select_fields} from `tab{doc.doctype} Item` where parent = %s""",
        doc.return_against,
        as_dict=1,
    ):
        valid_items = get_ref_item_dict(valid_items, d)

    for d in doc.get("items"):
        key = d.item_code
        ref = valid_items.get(key, frappe._dict())
        if (d.rate) != ref.rate:
            d.rate = ref.rate


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
    doc.taxes = []
    taxes = []
    taxes.append(
        {
            "charge_type": "Actual",
            "description": "Scheme Discount",
            "cost_center": "Main - VE",
            "included_in_print_rate": 0,
            "dont_recompute_tax": 1,
            "tax_amount": data.scheme_discount,
            "account_head": "Scheme Discount - VE",
        },
    )

    taxes.append(
        {
            "charge_type": "Actual",
            "description": "Cash Discount",
            "cost_center": "Main - VE",
            "included_in_print_rate": 0,
            "dont_recompute_tax": 1,
            "tax_amount": data.cash_discount,
            "account_head": "Cash Discount - VE",
        },
    )

    taxes.append(
        {
            "charge_type": "On Previous Row Total",
            "description": "CGST",
            "cost_center": "Main - VE",
            "included_in_print_rate": 0,
            "dont_recompute_tax": 2,
            "rate": 9,
            "account_head": "Output Tax CGST - VE",
            "row_id": 2,
        },
    )

    taxes.append(
        {
            "charge_type": "On Previous Row Total",
            "description": "SGST",
            "cost_center": "Main - VE",
            "included_in_print_rate": 0,
            "dont_recompute_tax": 1,
            "rate": 9,
            "account_head": "Output Tax SGST - VE",
            "row_id": 2,
        },
    )

    doc.update({"taxes": taxes})


def get_invoice_wise_data(data):
    invoices = frappe._dict()
    for row in data:
        row = frappe._dict(row)
        invoice_no = row.get("invoice_no.")
        is_return = row.document_type == "Credit Note"
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
                    "is_return": is_return,
                    "return_against": row.get("ref._invoice_no."),
                    "cash_discount": 0,
                    "scheme_discount": 0,
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
        scheme_discount = (row.get("scheme_discount_value")) + row.get(
            "coupon_discount_value"
        )
        cash_discount = row.get("mop_discount")

        item = frappe._dict(
            {
                "item_code": row.product_code,
                "description": row.description,
                "gst_hsn_code": row.hsn_number,
                "qty": qty,
                "uom": "Nos",
                "rate": rate,
                "cgst": (row.cgst_value * -1 if is_return else row.cgst_value),
                "sgst": (row.sgst_value * -1 if is_return else row.sgst_value),
                "scheme_discount": scheme_discount,
                "cash_discount": cash_discount,
                "gst_rate": 9,
                "total": row.get("total_value_incl_vat/gst"),
                "taxable_value": row.get("total_value_incl_vat/gst")
                - row.get("vat/gst"),
            }
        )

        inv["scheme_discount"] += scheme_discount
        inv["cash_discount"] += cash_discount

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

    # Calculate the total from the items
    for row in data.get("items", []):
        total += row.total

    # Calculate the difference between the grand total and the calculated total
    diff = total - doc.grand_total

    # Check if the difference is within the acceptable range
    if -1 <= diff <= 1:
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
    else:
        # Raise an error if the round off is greater than the allowed range
        frappe.msgprint("Round off is greater than 1")
