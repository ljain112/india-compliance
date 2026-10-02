# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_months, get_quarter_start, getdate, today

from india_compliance.gst_india.utils.tests import create_sales_invoice
from india_compliance.vat_india.doctype.c_form.c_form import (
    FINANCIAL_YEAR_QUARTERS,
    get_eligible_invoices,
)

# test_records = frappe.get_test_records('C-Form')

IGNORE_TEST_RECORD_DEPENDENCIES = ["Company", "Customer", "Sales Invoice", "Territory"]

COMPANY = "_Test Indian Registered Company"
CUSTOMER = "_Test Registered Customer"
INTER_STATE_ADDRESS = "_Test Registered Customer-Billing-3"
NON_GST_ITEM = "_Test Non GST Item"
TEST_USER = "test@example.com"


def make_c_form(invoices, **kwargs):
    return frappe.get_doc(
        {
            "doctype": "C-Form",
            "c_form_no": frappe.generate_hash(length=6),
            "received_date": today(),
            "customer": CUSTOMER,
            "company": COMPANY,
            "quarter": FINANCIAL_YEAR_QUARTERS[get_quarter_start(today()).month],
            "total_amount": 100,
            "state": "Karnataka",
            "invoices": [{"invoice_no": invoice.name} for invoice in invoices],
            **kwargs,
        }
    )


def search_invoices():
    return [
        row[0]
        for row in get_eligible_invoices(
            "Sales Invoice", "", "name", 0, 20, {"customer": CUSTOMER, "company": COMPANY}
        )
    ]


class TestCForm(IntegrationTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.invoice = create_sales_invoice(item_code=NON_GST_ITEM, customer_address=INTER_STATE_ADDRESS)
        cls.last_quarter_invoice = create_sales_invoice(
            item_code=NON_GST_ITEM,
            customer_address=INTER_STATE_ADDRESS,
            posting_date=add_months(get_quarter_start(today()), -1),
            set_posting_time=1,
        )
        cls.in_state_invoice = create_sales_invoice(item_code=NON_GST_ITEM)
        cls.taxable_invoice = create_sales_invoice(customer_address=INTER_STATE_ADDRESS, is_out_state=1)
        cls.draft_invoice = create_sales_invoice(
            item_code=NON_GST_ITEM, customer_address=INTER_STATE_ADDRESS, do_not_submit=True
        )
        cls.other_customer_invoice = create_sales_invoice(
            customer="_Test Registered Composition Customer",
            customer_address="_Test Registered Composition Customer-Billing",
            item_code=NON_GST_ITEM,
        )

        test_user = frappe.get_doc("User", TEST_USER)
        test_user.add_roles("Accounts User")
        cls.addClassCleanup(test_user.remove_roles, "Accounts User")
        cls.addClassCleanup(frappe.clear_cache, user=TEST_USER)
        frappe.clear_cache(user=TEST_USER)

    def test_c_form_workflow(self):
        invoice_details = {
            "invoice_date": getdate(self.invoice.posting_date),
            "territory": self.invoice.territory,
            "net_total": self.invoice.base_net_total,
            "grand_total": self.invoice.base_grand_total,
        }

        self.assertIn(self.invoice.name, search_invoices())
        self.assertNotIn(self.taxable_invoice.name, search_invoices())

        self.assertRaisesRegex(
            frappe.ValidationError,
            "not a valid Indian state",
            make_c_form([self.invoice], state="Unknown").insert,
        )
        self.assertRaisesRegex(
            frappe.ValidationError,
            rf"(?s)invalid(?=.*{self.draft_invoice.name})(?=.*{self.other_customer_invoice.name})",
            make_c_form([self.draft_invoice, self.other_customer_invoice]).insert,
        )
        self.assertRaisesRegex(
            frappe.ValidationError,
            rf"(?s)not eligible(?=.*{self.in_state_invoice.name})(?=.*{self.taxable_invoice.name})",
            make_c_form([self.in_state_invoice, self.taxable_invoice]).insert,
        )
        self.assertRaisesRegex(
            frappe.ValidationError,
            "only one quarter",
            make_c_form([self.invoice, self.last_quarter_invoice]).insert,
        )
        self.assertRaisesRegex(
            frappe.ValidationError,
            "Invoices belong to quarter",
            make_c_form([self.last_quarter_invoice]).insert,
        )

        with self.set_user(TEST_USER):
            c_form = make_c_form([self.invoice])
            self.assertDictEqual(c_form.get_invoice_details(self.invoice.name), invoice_details)

            c_form.invoices[0].grand_total = 1
            c_form.insert()
            c_form.submit()

            self.assertDocumentEqual(
                {
                    "total_invoiced_amount": self.invoice.base_grand_total,
                    "invoices": [{"invoice_no": self.invoice.name, **invoice_details}],
                },
                c_form,
            )
            self.assertNotIn(self.invoice.name, search_invoices())
            self.assertRaisesRegex(
                frappe.ValidationError,
                f"tagged in another C-form.*{c_form.name}",
                make_c_form([self.invoice]).insert,
            )

            c_form.cancel()
            self.assertIn(self.invoice.name, search_invoices())

            amended_c_form = frappe.copy_doc(c_form)
            amended_c_form.docstatus = 0
            amended_c_form.amended_from = c_form.name
            amended_c_form.insert()
            amended_c_form.submit()

            self.assertRaisesRegex(
                frappe.ValidationError, "at least 1 invoice", make_c_form([]).insert().submit
            )

        with self.set_user("Guest"):
            self.assertRaises(frappe.PermissionError, c_form.get_invoice_details, self.invoice.name)
