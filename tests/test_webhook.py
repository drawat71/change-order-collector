"""Tests for the webhook handler's paid-marking logic."""

import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.store import InvoiceStore  # noqa: E402
from app.webhook import process_webhook_event, run_server  # noqa: E402


def quiet_log(*args, **kwargs):
    pass


class ProcessEventTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = InvoiceStore(os.path.join(self.tmp.name, "store.json"))
        self.events_path = os.path.join(self.tmp.name, "events.jsonl")
        self.store.add_invoice("INV-TEST-1", {"status": "SENT"})

    def test_invoice_paid_marks_paid(self):
        event = {
            "id": "WH-1",
            "event_type": "INVOICING.INVOICE.PAID",
            "resource": {"id": "INV-TEST-1", "status": "PAID"},
        }
        result = process_webhook_event(
            event, self.store, self.events_path, log=quiet_log
        )
        self.assertEqual(result["invoice_id"], "INV-TEST-1")
        self.assertTrue(result["marked_paid"])
        self.assertEqual(self.store.get_invoice("INV-TEST-1")["status"], "PAID")
        with open(self.events_path, encoding="utf-8") as handle:
            lines = handle.read().strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["event_type"], "INVOICING.INVOICE.PAID")

    def test_capture_completed_with_invoice_id_marks_paid(self):
        event = {
            "id": "WH-2",
            "event_type": "PAYMENT.CAPTURES.COMPLETED",
            "resource": {
                "id": "CAPTURE-1",
                "supplementary_data": {
                    "related_ids": {"invoice_id": "INV-TEST-1"}
                },
            },
        }
        result = process_webhook_event(
            event, self.store, self.events_path, log=quiet_log
        )
        self.assertTrue(result["marked_paid"])
        self.assertEqual(self.store.get_invoice("INV-TEST-1")["status"], "PAID")

    def test_capture_completed_without_invoice_id_is_graceful(self):
        event = {
            "id": "WH-3",
            "event_type": "PAYMENT.CAPTURES.COMPLETED",
            "resource": {"id": "CAPTURE-2"},
        }
        result = process_webhook_event(
            event, self.store, self.events_path, log=quiet_log
        )
        self.assertFalse(result["marked_paid"])
        self.assertEqual(self.store.get_invoice("INV-TEST-1")["status"], "SENT")

    def test_unrelated_event_does_not_mark_paid(self):
        event = {
            "id": "WH-4",
            "event_type": "INVOICING.INVOICE.CREATED",
            "resource": {"id": "INV-TEST-1", "status": "DRAFT"},
        }
        result = process_webhook_event(
            event, self.store, self.events_path, log=quiet_log
        )
        self.assertFalse(result["marked_paid"])
        self.assertEqual(self.store.get_invoice("INV-TEST-1")["status"], "SENT")


class HttpWebhookTests(unittest.TestCase):
    def test_post_webhook_over_http(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = InvoiceStore(os.path.join(tmp, "store.json"))
            events_path = os.path.join(tmp, "events.jsonl")
            store.add_invoice("INV-HTTP-1", {"status": "SENT"})
            server = run_server("127.0.0.1", 0, store, events_path, log=quiet_log)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                payload = json.dumps({
                    "event_type": "INVOICING.INVOICE.PAID",
                    "resource": {"id": "INV-HTTP-1", "status": "PAID"},
                }).encode("utf-8")
                request = urllib.request.Request(
                    "http://127.0.0.1:%d/webhook" % port,
                    data=payload, method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with redirect_stdout(io.StringIO()):
                    with urllib.request.urlopen(request, timeout=10) as response:
                        body = json.loads(response.read().decode("utf-8"))
                self.assertTrue(body["marked_paid"])
                self.assertEqual(
                    store.get_invoice("INV-HTTP-1")["status"], "PAID"
                )
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
