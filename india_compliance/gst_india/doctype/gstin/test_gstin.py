# Copyright (c) 2023, Resilient Tech and Contributors
# See license.txt
import frappe
import responses
from frappe.tests import IntegrationTestCase, change_settings
from frappe.utils import getdate
from responses import matchers

from india_compliance.gst_india.api_classes.base import BASE_URL
from india_compliance.gst_india.doctype.gstin.gstin import (
    create_or_update_gstin_status,
    validate_gst_transporter_id,
)

TEST_GSTIN = "24AANFA2641L1ZK"

TRANSPORTER_ID_API_RESPONSE = {
    "success": True,
    "message": "Transporter details are fetched successfully",
    "result": {
        "transin": TEST_GSTIN,
        "tradeName": "_Test Transporter ID Comapany",
        "legalName": "_Test Transporter ID Comapany",
        "address1": "address 1",
        "address2": "address 2",
        "stateCode": "24",
        "pinCode": "390020",
    },
}

E_INVOICE_TEST_GSTIN = "24AAUPV7468F1ZW"
COMPANY_GSTIN = "24AAQCA8719H1ZC"
SYNC_GSTIN_URL = BASE_URL + "/test/ei/api/master/syncgstin"
E_INVOICE_SETTINGS = {"enable_api": 1, "enable_e_invoice": 1, "sandbox_mode": 1}

# as returned by the e-Invoice Portal, after syncing with the GST Common Portal
GSTIN_DETAILS = {
    "Gstin": E_INVOICE_TEST_GSTIN,
    "LegalName": "_Test Registered Company",
    "TradeName": "_Test Registered Company",
    "TxpType": "REG",
    "Status": "ACT",
    "BlkStatus": "U",
    "DtReg": "2017-07-01",
    "DtDReg": "",
    "StateCode": "24",
}


class TestGSTIN(IntegrationTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    @responses.activate
    @change_settings("GST Settings", {"validate_gstin_status": 1, "sandbox_mode": 0})
    def test_validate_gst_transporter_id(self):
        self.mock_get_transporter_details_response()

        validate_gst_transporter_id(TEST_GSTIN)

    def mock_get_transporter_details_response(self):
        url = "https://asp.resilient.tech/ewb/Master/GetTransporterDetails"

        responses.add(
            responses.GET,
            url,
            json=TRANSPORTER_ID_API_RESPONSE,
            match=[matchers.query_param_matcher({"trn_no": TEST_GSTIN})],
            status=200,
        )


class TestGSTINOnEInvoicePortal(IntegrationTestCase):
    """
    Test manual update of GSTIN details on the e-Invoice Portal, where the details are
    synced from the GST Common Portal.
    """

    def setUp(self):
        settings = frappe.get_doc("GST Settings")
        settings.set(
            "credentials",
            [
                {
                    "company": "_Test Indian Registered Company",
                    "gstin": COMPANY_GSTIN,
                    "service": "e-Waybill / e-Invoice",
                    "username": "test_username",
                    "password": "TestPass@123",
                }
            ],
        )
        settings.save(ignore_permissions=True)

        # outdated status, as available before syncing with the GST Common Portal
        self.gstin_doc = create_or_update_gstin_status(
            response=frappe._dict(
                {
                    "gstin": E_INVOICE_TEST_GSTIN,
                    "status": "CNL",
                    "is_blocked": "B",
                    "registration_date": getdate("2017-07-01"),
                    "cancelled_date": getdate("2024-01-01"),
                }
            )
        )

    @responses.activate
    @change_settings("GST Settings", E_INVOICE_SETTINGS)
    def test_update_gstin_on_e_invoice_portal(self):
        self.mock_sync_gstin_response(GSTIN_DETAILS)

        self.gstin_doc.update_gstin_on_e_invoice_portal()

        self.assertDocumentEqual(
            {
                "status": "Active",
                "is_blocked": 0,
                "registration_date": getdate("2017-07-01"),
                "cancelled_date": None,
            },
            frappe.get_doc("GSTIN", E_INVOICE_TEST_GSTIN),
        )

    @responses.activate
    @change_settings("GST Settings", E_INVOICE_SETTINGS)
    def test_block_status_on_e_invoice_portal(self):
        # blank block status is returned for unblocked GSTINs
        for block_status, is_blocked in (("B", 1), ("U", 0), ("", 0)):
            with self.subTest(block_status=block_status):
                self.mock_sync_gstin_response({**GSTIN_DETAILS, "BlkStatus": block_status})

                self.gstin_doc.update_gstin_on_e_invoice_portal()

                self.assertEqual(frappe.get_value("GSTIN", E_INVOICE_TEST_GSTIN, "is_blocked"), is_blocked)

    @responses.activate
    @change_settings("GST Settings", E_INVOICE_SETTINGS)
    def test_update_invalid_gstin_on_e_invoice_portal(self):
        # invalid GSTIN errors are ignored by the API, and returned without status
        responses.add(
            responses.GET,
            SYNC_GSTIN_URL,
            json={"success": False, "message": "3028 : GSTIN is invalid"},
            status=200,
        )

        self.assertRaisesRegex(
            frappe.ValidationError,
            "3028 : GSTIN is invalid",
            self.gstin_doc.update_gstin_on_e_invoice_portal,
        )

        # outdated status is retained
        self.assertDocumentEqual(
            {"status": "Cancelled", "is_blocked": 1},
            frappe.get_doc("GSTIN", E_INVOICE_TEST_GSTIN),
        )

    @responses.activate
    @change_settings("GST Settings", {"enable_api": 1, "enable_e_invoice": 0})
    def test_update_gstin_on_e_invoice_portal_without_credentials(self):
        # no API request is made, since no mocked response is registered
        self.assertRaisesRegex(
            frappe.ValidationError,
            "Please enable e-Invoicing and set e-Waybill / e-Invoice credentials",
            self.gstin_doc.update_gstin_on_e_invoice_portal,
        )

    @responses.activate
    @change_settings("GST Settings", E_INVOICE_SETTINGS)
    def test_gstin_status_is_fetched_without_sync(self):
        # automatic refresh must not sync GSTIN details on the e-Invoice Portal
        responses.add(
            responses.GET,
            BASE_URL + "/test/ei/api/master/gstin",
            json={"success": True, "result": GSTIN_DETAILS},
            match=[matchers.query_param_matcher({"gstin": E_INVOICE_TEST_GSTIN})],
            status=200,
        )

        create_or_update_gstin_status(E_INVOICE_TEST_GSTIN)

        self.assertEqual(len(responses.calls), 1)
        self.assertEqual(frappe.get_value("GSTIN", E_INVOICE_TEST_GSTIN, "status"), "Active")

    def mock_sync_gstin_response(self, result):
        responses.add(
            responses.GET,
            SYNC_GSTIN_URL,
            json={"success": True, "result": result},
            match=[matchers.query_param_matcher({"gstin": E_INVOICE_TEST_GSTIN})],
            status=200,
        )
