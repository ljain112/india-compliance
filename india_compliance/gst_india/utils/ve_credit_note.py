import frappe
from frappe.utils.data import getdate
from erpnext.accounts.doctype.chart_of_accounts_importer.chart_of_accounts_importer import (
    generate_data_from_excel,
    get_file,
)

CREDIT_NOTE_ACCOUNT = "Credit Note By Company - VE"


def import_invoices():
    file_name = "/private/files/Ledger_Report_19Nov2024_638676311193017942.xlsx"
    file_doc, extension = get_file(file_name)

    data = generate_data_from_excel(file_doc, extension, as_dict=True)

    for row in data:
        row = frappe._dict(row)
        print(row)
        print(row.credit, "row.credit")
        if row.particulars != "PROCESSING CREDIT NOTE":
            continue

        if frappe.db.get_value("Journal Entry", {"bill_no": row.document_no}):
            continue

        date = getdate(row.document_date)

        jv = frappe.new_doc("Journal Entry")
        jv.posting_date = date
        jv.voucher_type = "Credit Note"
        jv.bill_no = row.document_no
        jv.bill_date = date
        jv.user_remark = row.particulars

        jv.append(
            "accounts",
            {
                "account": "Debtors - VE",
                "party_type": "Customer",
                "party": row.account_code,
                "credit": row.credit,
                "debit": 0,
                "credit_in_account_currency": row.credit,
                "debit_in_account_currency": 0,
            },
        )

        jv.append(
            "accounts",
            {
                "account": CREDIT_NOTE_ACCOUNT,
                "debit_in_account_currency": row.credit,
                "credit_in_account_currency": 0,
                "debit": row.credit,
                "credit": 0,
            },
        )

        jv.set_missing_values()

        jv.insert()
        jv.save()
