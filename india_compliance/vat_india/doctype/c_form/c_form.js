// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

//c-form js file
// -----------------------------

frappe.ui.form.on("C-Form", {
    setup(frm) {
        frm.set_query("invoice_no", "invoices", (doc) => ({
            query: "india_compliance.vat_india.doctype.c_form.c_form.get_eligible_invoices",
            filters: {
                customer: doc.customer,
                company: doc.company,
            },
        }));
    },

    refresh(frm) {
        frm.get_field("state").set_data(frappe.boot.india_state_options || []);
    },
});

frappe.ui.form.on("C-Form Invoice Detail", {
    invoice_no(frm, cdt, cdn) {
        let d = frappe.get_doc(cdt, cdn);

        if (d.invoice_no) {
            frm.call("get_invoice_details", {
                invoice_no: d.invoice_no,
            }).then((r) => {
                frappe.model.set_value(cdt, cdn, r.message);
            });
        }
    },
});
