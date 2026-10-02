# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _, bold
from frappe.model.document import Document
from frappe.utils import flt, get_quarter_start

from india_compliance.gst_india.constants import INDIAN_STATES
from india_compliance.gst_india.overrides.transaction import is_inter_state_supply

INVOICE_DETAIL_FIELDS = {
    "invoice_date": "posting_date",
    "territory": "territory",
    "net_total": "base_net_total",
    "grand_total": "base_grand_total",
}

FINANCIAL_YEAR_QUARTERS = {4: "I", 7: "II", 10: "III", 1: "IV"}


class CForm(Document):
    def validate(self):
        """Validate invoice that c-form is applicable
        and no other c-form is received for that"""

        self._validate_state()
        invoices = self._get_invoices()
        self._validate_invoices(invoices)
        self._set_invoice_details(invoices)
        self.set_total_invoiced_amount()

    def _validate_state(self):
        if self.state and self.state not in INDIAN_STATES:
            frappe.throw(_("{0} is not a valid Indian state").format(bold(self.state)))

    @property
    def _invoice_names(self):
        return [d.invoice_no for d in self.get("invoices") if d.invoice_no]

    def _get_invoices(self):
        if not self._invoice_names:
            return []

        invoice_filters = {"name": ("in", self._invoice_names), "docstatus": 1, "customer": self.customer}
        if self.company:
            invoice_filters["company"] = self.company

        return frappe.get_all(
            "Sales Invoice",
            filters=invoice_filters,
            fields=[
                "name",
                "gst_category",
                "place_of_supply",
                "company_gstin",
                *(f"{source} as {field}" for field, source in INVOICE_DETAIL_FIELDS.items()),
            ],
        )

    def _validate_invoices(self, invoices):
        if not self._invoice_names:
            return

        self._validate_invalid_invoices(invoices)
        self._validate_ineligible_invoices(invoices)
        self._validate_quarter(invoices)
        self._validate_tagged_invoices()

    def _validate_invalid_invoices(self, invoices):
        valid_invoices = {invoice.name for invoice in invoices}
        invalid_invoices = [name for name in self._invoice_names if name not in valid_invoices]

        if invalid_invoices:
            frappe.throw(
                _(
                    "Following invoices are invalid. They might be cancelled, do not exist or belong to another customer or company:<br>{0}"
                ).format(", ".join(bold(name) for name in invalid_invoices))
            )

    def _validate_ineligible_invoices(self, invoices):
        non_gst_invoices = set(
            frappe.get_all(
                "Sales Invoice Item",
                filters={
                    "parenttype": "Sales Invoice",
                    "parent": ("in", [invoice.name for invoice in invoices]),
                    "gst_treatment": "Non-GST",
                },
                pluck="parent",
                distinct=True,
            )
        )

        ineligible_invoices = [
            invoice.name
            for invoice in invoices
            if invoice.name not in non_gst_invoices
            or not is_inter_state_supply(frappe._dict({**invoice, "doctype": "Sales Invoice"}))
        ]

        if ineligible_invoices:
            frappe.throw(
                _(
                    "C-form is applicable only for inter-state sale of Non-GST goods. Following invoices are not eligible:<br>{0}"
                ).format(", ".join(bold(name) for name in ineligible_invoices))
            )

    def _validate_quarter(self, invoices):
        quarter_starts = {get_quarter_start(invoice.invoice_date) for invoice in invoices}

        if len(quarter_starts) > 1:
            frappe.throw(_("C-form can include invoices of only one quarter of a financial year"))

        quarter = FINANCIAL_YEAR_QUARTERS[quarter_starts.pop().month]

        if self.quarter and self.quarter != quarter:
            frappe.throw(
                _("Invoices belong to quarter {0}, but quarter {1} is selected").format(
                    bold(quarter), bold(self.quarter)
                )
            )

    def _validate_tagged_invoices(self):
        tagged_invoices = frappe.get_all(
            "C-Form Invoice Detail",
            filters={
                "invoice_no": ("in", self._invoice_names),
                "parent": ("!=", self.name),
                "docstatus": 1,
            },
            fields=["invoice_no", "parent"],
        )

        if tagged_invoices:
            frappe.throw(
                _(
                    "Following invoices are tagged in another C-form. Remove them from that C-form and try again:<br>{0}"
                ).format(
                    "<br>".join(f"{bold(row.invoice_no)} - {bold(row.parent)}" for row in tagged_invoices)
                )
            )

    def _set_invoice_details(self, invoices):
        invoices = {invoice.name: invoice for invoice in invoices}

        for row in self.get("invoices"):
            if invoice := invoices.get(row.invoice_no):
                row.update({field: invoice[field] for field in INVOICE_DETAIL_FIELDS})

    def set_total_invoiced_amount(self):
        self.total_invoiced_amount = sum(flt(d.grand_total) for d in self.get("invoices"))

    def on_submit(self):
        if not self.get("invoices"):
            frappe.throw(_("Please enter at least 1 invoice in the table"))

    @frappe.whitelist()
    def get_invoice_details(self, invoice_no: str):
        """Pull details from invoice for reference"""

        if not invoice_no:
            return

        frappe.has_permission("Sales Invoice", "read", invoice_no, throw=True)

        return frappe.db.get_value(
            "Sales Invoice",
            invoice_no,
            [f"{source} as {field}" for field, source in INVOICE_DETAIL_FIELDS.items()],
            as_dict=True,
        )


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_eligible_invoices(
    doctype: str | None = None,
    txt: str | None = None,
    searchfield: str | None = None,
    start: int | None = None,
    page_len: int | None = None,
    filters: str | dict | frappe._dict | None = None,
):
    filters = frappe._dict(filters)

    c_form = frappe.qb.DocType("C-Form")
    c_form_invoice = frappe.qb.DocType("C-Form Invoice Detail")

    tagged_invoices = (
        frappe.qb.from_(c_form_invoice)
        .join(c_form)
        .on(c_form.name == c_form_invoice.parent)
        .select(c_form_invoice.invoice_no)
        .where(c_form.docstatus == 1)
        .where(c_form.customer == filters.customer)
        .run(pluck=True)
    )

    _filters = [
        ["docstatus", "=", 1],
        ["customer", "=", filters.customer],
        ["Sales Invoice Item", "gst_treatment", "=", "Non-GST"],
    ]

    if filters.company:
        _filters.append(["company", "=", filters.company])

    if tagged_invoices:
        _filters.append(["name", "not in", tagged_invoices])

    if txt:
        _filters.append(["name", "like", f"%{txt}%"])

    return frappe.get_list(
        "Sales Invoice",
        filters=_filters,
        fields=["name", "posting_date"],
        distinct=True,
        start=start,
        page_length=page_len,
        as_list=True,
    )
