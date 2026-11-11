"""Tests for the mock PayPal flow and the proof CLI."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.paypal_client import (  # noqa: E402
    PayPalClient,
    PayPalConfig,
    PayPalConfigError,
    build_invoice_payload,
)
from app.proof import run_proof  # noqa: E402


class MockClientTests(unittest.TestCase):
    def setUp(self):
        self.client = PayPalClient(config=PayPalConfig(mock=True))

    def test_mock_token(self):
        token = self.client.get_access_token()
        self.assertTrue(token)
        self.assertIn("MOCK", token)

    def test_mock_create_and_send_invoice(self):
        created = self.client.create_invoice(
            billing_email="homeowner@example.com",
            item_name="Change order: extra outlet",
            amount="450.00",
            currency="USD",
        )
        self.assertEqual(created["status"], "DRAFT")
        self.assertTrue(created["id"].startswith("INV-MOCK-"))
        sent = self.client.send_invoice(created["id"])
        self.assertEqual(sent["status"], "SENT")

    def test_invoice_payload_shape(self):
        payload = build_invoice_payload(
            billing_email="homeowner@example.com",
            item_name="Extra work",
            amount="125.50",
            quantity="2",
            currency="CAD",
            invoicer_email="contractor@example.com",
        )
        self.assertEqual(payload["detail"]["currency_code"], "CAD")
        self.assertEqual(
            payload["invoicer"]["email_address"], "contractor@example.com"
        )
        self.assertEqual(
            payload["primary_recipients"][0]["billing_info"]["email_address"],
            "homeowner@example.com",
        )
        self.assertEqual(len(payload["items"]), 1)
        item = payload["items"][0]
        self.assertEqual(item["name"], "Extra work")
        self.assertEqual(item["quantity"], "2")
        self.assertEqual(item["unit_amount"]["value"], "125.50")
        self.assertEqual(item["unit_amount"]["currency_code"], "CAD")

    def test_missing_credentials_raise_helpful_error(self):
        config = PayPalConfig(
            client_id="", client_secret="", mock=False, load_env_file=False
        )
        # Force empty credentials regardless of the ambient environment.
        config.client_id = ""
        config.client_secret = ""
        client = PayPalClient(config=config)
        with self.assertRaises(PayPalConfigError) as ctx:
            client.get_access_token()
        self.assertIn("README", str(ctx.exception))


class LiveClientTests(unittest.TestCase):
    def test_create_invoice_normalizes_self_href(self):
        config = PayPalConfig(client_id="test", client_secret="test",
                              mock=False, load_env_file=False)
        client = PayPalClient(config=config)
        client._access_token = "test-token"
        href = "https://api-m.sandbox.paypal.com/v2/invoicing/invoices/INV-123"
        for response in (
            {"rel": "self", "href": href, "method": "GET"},
            {"links": [{"rel": "self", "href": href, "method": "GET"}]},
        ):
            with self.subTest(response=response):
                client._request = lambda *args, **kwargs: response.copy()
                created = client.create_invoice(billing_email="homeowner@example.com")
                self.assertEqual(created["id"], "INV-123")
                self.assertEqual(created["href"], href)


class ProofTests(unittest.TestCase):
    def test_mock_proof_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            passed, results = run_proof(mock=True, data_dir=tmp)
            self.assertTrue(passed, results)
            for key in (
                "token",
                "invoice_created",
                "invoice_sent",
                "webhook_received",
                "invoice_marked_paid",
            ):
                self.assertTrue(results[key], key)
            # The raw webhook event was appended to the events file.
            events_path = os.path.join(tmp, "events.jsonl")
            self.assertTrue(os.path.exists(events_path))
            with open(events_path, encoding="utf-8") as handle:
                contents = handle.read()
            self.assertIn("INVOICING.INVOICE.PAID", contents)


if __name__ == "__main__":
    unittest.main()
