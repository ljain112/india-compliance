// Copyright (c) 2023, Resilient Tech and contributors
// For license information, please see license.txt

frappe.ui.form.on("GSTIN", {
    refresh(frm) {
        frm.disable_form();

        frm.add_custom_button(__("GSTIN Status"), () => frm.call("update_gstin_status"), __("Update GSTIN"));

        frm.add_custom_button(
            __("Transporter ID Status"),
            () => frm.call("update_transporter_id_status"),
            __("Update GSTIN"),
        );

        if (!india_compliance.is_e_invoice_enabled()) return;

        frm.add_custom_button(__("Update GSTIN on e-Invoice Portal"), () =>
            frm.call("update_gstin_on_e_invoice_portal").then(() =>
                frappe.show_alert({
                    message: __("GSTIN Status is {0}", [__(frm.doc.status)]),
                    indicator: "green",
                }),
            ),
        );
    },
});
