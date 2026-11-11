"""Webhook receiver for PayPal events.

Uses http.server from the standard library. The endpoint is:

    POST /webhook

Every received event is appended as raw JSON (one line) to a local
events file (JSONL). When the event type is INVOICING.INVOICE.PAID the
related invoice is marked PAID in the local InvoiceStore.
PAYMENT.CAPTURES.COMPLETED is handled gracefully the same way when it
carries a related invoice id, and otherwise just logged.

The event-processing logic lives in process_webhook_event() so it can
be unit tested without starting a server.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAID_EVENT_TYPES = ("INVOICING.INVOICE.PAID",)
CAPTURE_EVENT_TYPES = ("PAYMENT.CAPTURES.COMPLETED",)


def extract_invoice_id(event):
    """Best-effort extraction of an invoice id from a webhook event."""
    if not isinstance(event, dict):
        return None
    resource = event.get("resource") or {}
    if isinstance(resource, dict):
        # An invoice resource carries its own id.
        if resource.get("id") and (
            "detail" in resource or resource.get("status") in
            ("PAID", "SENT", "DRAFT", "MARKED_AS_PAID")
        ):
            return resource["id"]
        if resource.get("invoice_id"):
            return resource["invoice_id"]
        supplementary = resource.get("supplementary_data") or {}
        related = supplementary.get("related_ids") or {}
        if related.get("invoice_id"):
            return related["invoice_id"]
        if resource.get("id") and event.get("event_type", "").startswith("INVOICING."):
            return resource["id"]
    return event.get("resource_id") or None


def append_event(events_path, event):
    directory = os.path.dirname(os.path.abspath(events_path))
    os.makedirs(directory, exist_ok=True)
    with open(events_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def process_webhook_event(event, store, events_path=None, log=print):
    """Process one parsed webhook event.

    Appends the event to events_path (if given), logs its type and
    related invoice id, and marks the invoice paid when appropriate.
    Returns a dict describing what happened.
    """
    event_type = event.get("event_type", "UNKNOWN") if isinstance(event, dict) else "UNKNOWN"
    invoice_id = extract_invoice_id(event)
    if events_path:
        append_event(events_path, event)
    log("webhook: event_type=%s invoice_id=%s" % (event_type, invoice_id))

    marked_paid = False
    if event_type in PAID_EVENT_TYPES and invoice_id:
        store.mark_paid(invoice_id)
        marked_paid = True
        log("webhook: invoice %s marked PAID" % invoice_id)
    elif event_type in CAPTURE_EVENT_TYPES:
        # A capture may be tied to an invoice order. Mark it when we can
        # identify the invoice; otherwise logging it is enough.
        if invoice_id:
            store.mark_paid(invoice_id)
            marked_paid = True
            log("webhook: invoice %s marked PAID (capture)" % invoice_id)
        else:
            log("webhook: capture event with no invoice id, logged only")
    return {
        "event_type": event_type,
        "invoice_id": invoice_id,
        "marked_paid": marked_paid,
    }


def make_handler(store, events_path, client=None, log=print):
    """Build a request handler class bound to a store and events file."""

    class WebhookHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # keep test output clean
            log("http: " + (fmt % args))

        def do_GET(self):
            if self.path in ("/", "/health"):
                body = b'{"status": "ok"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path != "/webhook":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            headers = {k: v for k, v in self.headers.items()}

            if client is not None:
                verified, message = client.verify_webhook_signature(headers, raw)
                log("webhook: signature check: %s" % message)
                if not verified:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'{"error": "signature verification failed"}')
                    return
            try:
                event = json.loads(raw.decode("utf-8") if raw else "{}")
            except ValueError:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error": "invalid JSON"}')
                return
            result = process_webhook_event(event, store, events_path, log=log)
            body = json.dumps(result).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return WebhookHandler


def run_server(host, port, store, events_path, client=None, log=print):
    handler = make_handler(store, events_path, client=client, log=log)
    server = ThreadingHTTPServer((host, port), handler)
    log("webhook server listening on http://%s:%s/webhook" % (host, port))
    return server
