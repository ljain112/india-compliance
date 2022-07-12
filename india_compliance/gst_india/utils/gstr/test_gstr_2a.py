from datetime import date, timedelta
from unittest.mock import Mock, patch

import frappe
from frappe import parse_json, read_file
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_datetime

from india_compliance.gst_india.utils import get_data_file_path
from india_compliance.gst_india.utils.gstr import (
    GSTRCategory,
    ReturnType,
    download_gstr_2a,
    save_gstr_2a,
)


class TestGSTRMixin:
    def get_doc(self, category):
        docname = frappe.get_value(
            self.doctype,
            {"company_gstin": self.gstin, "classification": category.value},
        )
        self.assertIsNotNone(docname)
        return frappe.get_doc(self.doctype, docname)

    def assertDownloadLog(self, category=None):
        if category:
            return_type = ReturnType.GSTR2A
        else:
            return_type = ReturnType.GSTR2B

        filters = {"gstin": self.gstin, "return_type": return_type}
        if category:
            filters["classification"] = category.value

        docname, last_updated_on = frappe.get_value(
            self.log_doctype, filters, ["name", "last_updated_on"]
        )
        self.assertIsNotNone(docname)
        self.assertAlmostEqual(
            last_updated_on, get_datetime(), delta=timedelta(minutes=2)
        )


class TestGSTR2a(FrappeTestCase, TestGSTRMixin):
    # Tests as per version 2.1 of GSTR2A Dt: 14-10-2020
    # TODO: make tests for individual categories
    @classmethod
    def setUpClass(cls):
        cls.gstin = "01AABCE2207R1Z5"
        cls.return_period = "032020"
        cls.doctype = "Inward Supply"
        cls.log_doctype = "GSTR Import Log"
        cls.test_data = parse_json(read_file(get_data_file_path("test_gstr_2a.json")))

        save_gstr_2a(
            cls.gstin,
            cls.return_period,
            cls.test_data.copy(),
        )

    @classmethod
    def tearDownClass(cls):
        frappe.db.delete(cls.doctype, {"company_gstin": cls.gstin})
        frappe.db.delete(cls.log_doctype, {"gstin": cls.gstin})

    @patch("india_compliance.gst_india.utils.gstr.save_gstr")
    @patch("india_compliance.gst_india.utils.gstr.GSTR2aAPI")
    def test_download_gstr_2a(self, mock_gstr_2a_api, mock_save_gstr):
        def mock_get_data(action, return_period, otp):
            if action in ["B2B", "B2BA", "CDN", "CDNA"]:
                return frappe._dict({action.lower(): self.test_data[action.lower()]})
            else:
                return frappe._dict(error_type="no_docs_found")

        def mock_save_gstr_func(gstin, return_type, return_period, json_data):
            self.assertEqual(gstin, self.gstin)
            self.assertEqual(return_period, self.return_period)
            self.assertTrue("cdnr" in json_data)
            self.assertTrue("cdnra" in json_data)
            self.assertTrue("isd" not in json_data)
            self.assertListEqual(json_data.cdnr, self.test_data.cdn)

        mock_gstr_2a_api.return_value = Mock()
        mock_gstr_2a_api.return_value.get_data.side_effect = mock_get_data
        mock_save_gstr.side_effect = mock_save_gstr_func
        download_gstr_2a(self.gstin, {self.return_period})

    def test_gstr2a_b2b(self):
        doc = self.get_doc(GSTRCategory.B2B)
        self.assertDownloadLog(GSTRCategory.B2B)
        self.assertDocumentEqual(
            {
                "doc_date": date(2016, 11, 24),
                "doc_number": "S008400",
                "doc_type": "Invoice",
                "supplier_gstin": "01AABCE2207R1Z5",
                "supply_type": "Regular",
                "place_of_supply": "06-Haryana",
                "items": [
                    {
                        "item_number": 1,
                        "taxable_value": 400,
                        "rate": 5.00,
                        "igst": 0,
                        "cgst": 200,
                        "sgst": 200,
                        "cess": 0,
                    },
                ],
                "document_value": 729248.16,
                "diffprcnt": "1",
                "other_return_period": "122018",
                "amendment_type": "Receiver GSTIN Amended",
                "sup_return_period": "112019",
                "gstr_1_filled": 1,
                "gstr_3b_filled": 1,
                "gstr_1_filing_date": date(2019, 11, 18),
                "registration_cancel_date": date(2019, 8, 27),
            },
            doc,
        )

    def test_gstr2a_b2ba(self):
        doc = self.get_doc(GSTRCategory.B2BA)
        self.assertDownloadLog(GSTRCategory.B2BA)
        self.assertDocumentEqual(
            {
                "doc_date": date(2016, 11, 24),
                "doc_number": "S008400",
                "doc_type": "Invoice",
                "supplier_gstin": "01AABCE2207R1Z5",
                "supply_type": "Regular",
                "place_of_supply": "06-Haryana",
                "items": [
                    {
                        "item_number": 1,
                        "taxable_value": 6210.99,
                        "rate": 1.00,
                        "igst": 0,
                        "cgst": 614.44,
                        "sgst": 5.68,
                        "cess": 621.09,
                    },
                    {
                        "item_number": 2,
                        "taxable_value": 1000.05,
                        "rate": 2.00,
                        "igst": 0,
                        "cgst": 887.44,
                        "sgst": 5.68,
                        "cess": 50.12,
                    },
                ],
                "document_value": 729248.16,
                "diffprcnt": "0.65",
                "other_return_period": "122018",
                "amendment_type": "Receiver GSTIN Amended",
                "original_doc_number": "S008400",
                "original_doc_date": date(2016, 11, 24),
                "is_amended": 1,
                "sup_return_period": "042018",
                "gstr_1_filled": 1,
                "gstr_3b_filled": 1,
                "gstr_1_filing_date": date(2020, 5, 12),
                "registration_cancel_date": date(2019, 8, 27),
            },
            doc,
        )

    def test_gstr2a_cdn(self):
        doc = self.get_doc(GSTRCategory.CDNR)
        self.assertDownloadLog(GSTRCategory.CDNR)
        self.assertDocumentEqual(
            {
                "doc_date": date(2018, 9, 23),
                "doc_number": "533515",
                "doc_type": "Credit Note",
                "supplier_gstin": "01AAAAP1208Q1ZS",
                "supply_type": "Regular",
                "place_of_supply": "06-Haryana",
                "items": [
                    {
                        "item_number": 1,
                        "taxable_value": 6210.99,
                        "rate": 10.1,
                        "igst": 0,
                        "cgst": 614.44,
                        "sgst": 5.68,
                        "cess": 621.09,
                    }
                ],
                "document_value": 729248.16,
                "diffprcnt": "0.65",
                "other_return_period": "122018",
                "amendment_type": "Receiver GSTIN Amended",
                "sup_return_period": "042018",
                "gstr_1_filled": 1,
                "gstr_3b_filled": 1,
                "gstr_1_filing_date": date(2020, 5, 12),
                "registration_cancel_date": date(2019, 8, 27),
                "irn_source": "e-Invoice",
                "irn_number": (
                    "897ADG56RTY78956HYUG90BNHHIJK453GFTD99845672FDHHHSHGFH4567FG56TR"
                ),
                "irn_gen_date": date(2019, 12, 24),
            },
            doc,
        )

    def test_gstr2a_cdna(self):
        doc = self.get_doc(GSTRCategory.CDNRA)
        self.assertDownloadLog(GSTRCategory.CDNRA)
        self.assertDocumentEqual(
            {
                "doc_date": date(2018, 9, 23),
                "doc_number": "533515",
                "doc_type": "Credit Note",
                "supplier_gstin": "01AAAAP1208Q1ZS",
                "supply_type": "Regular",
                "place_of_supply": "01-Jammu and Kashmir",
                "items": [
                    {
                        "item_number": 1,
                        "taxable_value": 400,
                        "igst": 0,
                        "cgst": 200,
                        "sgst": 200,
                        "cess": 0,
                    }
                ],
                "document_value": 729248.16,
                "diffprcnt": "1",
                "other_return_period": "122018",
                "amendment_type": "Receiver GSTIN Amended",
                "original_doc_number": "533515",
                "original_doc_date": date(2016, 9, 23),
                "original_doc_type": "Credit Note",
                "sup_return_period": "112019",
                "gstr_1_filled": 1,
                "gstr_3b_filled": 1,
                "gstr_1_filing_date": date(2019, 11, 18),
                "registration_cancel_date": date(2019, 8, 27),
            },
            doc,
        )

    def test_gstr2a_isd(self):
        doc = self.get_doc(GSTRCategory.ISD)
        self.assertDownloadLog(GSTRCategory.ISD)
        self.assertDocumentEqual(
            {
                "doc_date": date(2016, 3, 3),
                "doc_number": "S0080",
                "doc_type": "ISD Invoice",
                "supplier_gstin": "16DEFPS8555D1Z7",
                "itc_availability": "Yes",
                "other_return_period": "122018",
                "amendment_type": "Receiver GSTIN Amended",
                "is_amended": 1,
                "document_value": 80,
                "items": [
                    {
                        "igst": 20,
                        "cgst": 20,
                        "sgst": 20,
                        "cess": 20,
                    }
                ],
            },
            doc,
        )

    def test_gstr2a_isda(self):
        # No such API exists. Its merged with ISD.
        pass

    def test_gstr2a_impg(self):
        doc = self.get_doc(GSTRCategory.IMPG)
        self.assertDownloadLog(GSTRCategory.IMPG)
        self.assertDocumentEqual(
            {
                "doc_date": date(2019, 11, 18),
                "port_code": "18272A",
                "doc_number": "2566282",
                "doc_type": "Bill of Entry",
                "is_amended": 0,
                "document_value": 246.54,
                "items": [
                    {
                        "taxable_value": 123.02,
                        "igst": 123.02,
                        "cess": 0.5,
                    }
                ],
            },
            doc,
        )

    def test_gstr2a_impgsez(self):
        doc = self.get_doc(GSTRCategory.IMPGSEZ)
        self.assertDownloadLog(GSTRCategory.IMPGSEZ)
        self.assertDocumentEqual(
            {
                "doc_date": date(2019, 11, 18),
                "port_code": "18272A",
                "doc_number": "2566282",
                "doc_type": "Bill of Entry",
                "supplier_gstin": self.gstin,
                "supplier_name": "GSTN",
                "is_amended": 0,
                "document_value": 246.54,
                "items": [
                    {
                        "taxable_value": 123.02,
                        "igst": 123.02,
                        "cgst": 0,
                        "sgst": 0,
                        "cess": 0.5,
                    }
                ],
            },
            doc,
        )
