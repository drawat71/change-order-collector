"""Small local invoice store backed by a single JSON file.

Standard library only. The store is intentionally simple: it is the
local reconciliation record the webhook handler updates when PayPal
reports an invoice as paid. It is not a production database.
"""

from __future__ import annotations

import json
import os
import threading


class InvoiceStore:
    """Thread-safe JSON-file store keyed by invoice id."""

    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.Lock()
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        if not os.path.exists(self.path):
            self._write({})

    def _read(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
        return {}

    def _write(self, data):
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
        os.replace(tmp_path, self.path)

    def add_invoice(self, invoice_id, record=None):
        """Insert or update an invoice record, defaulting status to DRAFT."""
        record = dict(record or {})
        record.setdefault("id", invoice_id)
        record.setdefault("status", "DRAFT")
        with self._lock:
            data = self._read()
            existing = data.get(invoice_id, {})
            existing.update(record)
            data[invoice_id] = existing
            self._write(data)
            return dict(existing)

    def get_invoice(self, invoice_id):
        with self._lock:
            data = self._read()
            record = data.get(invoice_id)
            return dict(record) if record else None

    def set_status(self, invoice_id, status):
        with self._lock:
            data = self._read()
            record = data.get(invoice_id, {"id": invoice_id})
            record["status"] = status
            data[invoice_id] = record
            self._write(data)
            return dict(record)

    def mark_sent_unless_paid(self, invoice_id):
        with self._lock:
            data = self._read()
            record = data[invoice_id]
            if record.get("status") != "PAID":
                record["status"] = "SENT"
                self._write(data)
            return dict(record)

    def mark_paid(self, invoice_id):
        """Mark an invoice PAID, creating a minimal record if unknown."""
        return self.set_status(invoice_id, "PAID")

    def all_invoices(self):
        with self._lock:
            return dict(self._read())
