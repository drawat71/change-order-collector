"""Local change-order workflow. This is a single-process demo store."""
import datetime
import json
import os
import re
import secrets
import threading
from decimal import Decimal, InvalidOperation


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class Orders:
    def __init__(self, path, invoices, client, summarizer):
        self.path, self.invoices, self.client, self.summarizer = path, invoices, client, summarizer
        self.lock = threading.RLock()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        if not os.path.exists(path):
            self._write({})

    def _read(self):
        with open(self.path, encoding='utf-8') as f:
            return json.load(f)

    def _write(self, data):
        with open(self.path + '.tmp', 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        os.replace(self.path + '.tmp', self.path)

    def all(self):
        with self.lock:
            return list(self._read().values())

    def get(self, order_id):
        with self.lock:
            return self._read().get(order_id)

    def create(self, title, note, amount, homeowner, email, photo=None):
        title, note, homeowner, email = (str(x).strip() for x in (title, note, homeowner, email))
        if not all((title, note, homeowner, email)) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            raise ValueError('Please provide a title, note, homeowner name and valid email.')
        if max(map(len, (title, note, homeowner, email))) > 4000 or len(title) > 120:
            raise ValueError('A field is too long.')
        try:
            value = Decimal(str(amount))
            if not value.is_finite() or value <= 0 or value > Decimal('1000000') or value.as_tuple().exponent < -2:
                raise ValueError()
        except (InvalidOperation, ValueError):
            raise ValueError('Amount must be positive, at most 1,000,000, with no more than two decimals.')
        order = dict(id=secrets.token_urlsafe(18), approval_token=secrets.token_urlsafe(32), title=title,
                     note=note, amount=f'{value:.2f}', homeowner=homeowner, email=email, photo=photo,
                     summary='', approval='PENDING', decision_at=None, invoice_id=None, created_at=now())
        order['summary'] = self.summarizer.summarize(order)
        with self.lock:
            data = self._read(); data[order['id']] = order; self._write(data)
        return order

    def by_token(self, token):
        return next((o for o in self.all() if secrets.compare_digest(o['approval_token'], token)), None)

    def decide(self, token, decision):
        if decision not in ('APPROVED', 'DECLINED'):
            raise ValueError('Invalid decision.')
        with self.lock:
            data = self._read()
            order = next((o for o in data.values() if secrets.compare_digest(o['approval_token'], token)), None)
            if not order:
                raise ValueError('Approval link not found.')
            if order['approval'] != 'PENDING':
                raise ValueError('This change order already has a decision.')
            order['approval'], order['decision_at'] = decision, now()
            self._write(data)
            return order

    def invoice(self, order_id):
        with self.lock:
            data = self._read(); order = data.get(order_id)
            if not order or order['approval'] != 'APPROVED':
                raise ValueError('An approved change order is required before invoicing.')
            if order['invoice_id']:
                raise ValueError('An invoice has already been created for this change order.')
            created = self.client.create_invoice(billing_email=order['email'], item_name=order['title'],
                amount=order['amount'], currency='USD', note=order['summary'])
            invoice_id = created.get('id')
            if invoice_id and self.client.config.mock:
                invoice_id = 'INV-MOCK-' + secrets.token_hex(12).upper()
            if not invoice_id:
                raise ValueError('PayPal returned no invoice ID.')
            # Persist the draft before sending, so a send failure cannot silently create another invoice.
            order['invoice_id'] = invoice_id
            self.invoices.add_invoice(invoice_id, {'status': 'DRAFT', 'order_id': order_id})
            self._write(data)
            self.client.send_invoice(invoice_id)
            # A webhook may have arrived while send was in progress.
            self.invoices.mark_sent_unless_paid(invoice_id)
            return order
