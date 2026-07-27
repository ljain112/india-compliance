import frappe


def execute():
    """
    Set Has Ship To Details where the e-Invoice was reported with them.

    Ship To details sent during IRN generation can't be modified for B2B and SEZ
    transactions, so the e-Waybill by IRN relies on this to know whether to send them.
    ERROR CODE: 2324
    """
    e_invoice_log = frappe.qb.DocType("e-Invoice Log")

    (
        frappe.qb.update(e_invoice_log)
        .set(e_invoice_log.has_ship_to_details, 1)
        .where(e_invoice_log.invoice_data.like("%ShipDtls%"))
    ).run()
