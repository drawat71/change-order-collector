import io
import json
import os
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from app.orders import Orders
from app.paypal_client import PayPalClient, PayPalConfig
from app.store import InvoiceStore
from app.summarizer import LocalSummarizer, HTTPSummarizer, configured_summarizer
from app.web import make_app

class OrderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.invoices = InvoiceStore(os.path.join(self.tmp.name, 'store.json'))
        self.client = PayPalClient(config=PayPalConfig(mock=True))
        self.orders = Orders(os.path.join(self.tmp.name, 'orders.json'), self.invoices, self.client, LocalSummarizer())
    def create(self): return self.orders.create('Outlet', 'Add an outlet.', '450.00', 'Alex', 'alex@example.com')
    def test_summary_and_persistence(self):
        o = self.create(); self.assertIn('Add an outlet.', o['summary']); self.assertIn('$450.00', o['summary']); self.assertEqual(self.orders.get(o['id'])['approval'], 'PENDING')
    def test_validation(self):
        for amount in ['0', '-1', '1.001', 'NaN', '1000001']:
            with self.subTest(amount=amount), self.assertRaises(ValueError): self.orders.create('A', 'B', amount, 'C', 'a@example.com')
        with self.assertRaises(ValueError): self.orders.create('A', 'B', '1', 'C', 'bad')
    def test_approval_gate_and_one_invoice(self):
        o = self.create()
        with self.assertRaises(ValueError): self.orders.invoice(o['id'])
        self.orders.decide(o['approval_token'], 'APPROVED'); result = self.orders.invoice(o['id'])
        self.assertEqual(self.invoices.get_invoice(result['invoice_id'])['status'], 'SENT')
        with self.assertRaises(ValueError): self.orders.invoice(o['id'])
    def test_decline_is_final_and_blocks_invoice(self):
        o = self.create(); result = self.orders.decide(o['approval_token'], 'DECLINED')
        self.assertTrue(result['decision_at'])
        with self.assertRaises(ValueError): self.orders.decide(o['approval_token'], 'APPROVED')
        with self.assertRaises(ValueError): self.orders.invoice(o['id'])
    def test_send_failure_preserves_draft(self):
        o = self.create(); self.orders.decide(o['approval_token'], 'APPROVED')
        with patch.object(self.client, 'send_invoice', side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError): self.orders.invoice(o['id'])
        saved = self.orders.get(o['id']); self.assertEqual(self.invoices.get_invoice(saved['invoice_id'])['status'], 'DRAFT')
        with self.assertRaises(ValueError): self.orders.invoice(o['id'])
    def test_sent_does_not_overwrite_paid(self):
        self.invoices.add_invoice('i', {'status': 'PAID'}); self.invoices.mark_sent_unless_paid('i'); self.assertEqual(self.invoices.get_invoice('i')['status'], 'PAID')
    def test_tokens_are_unique(self):
        self.assertNotEqual(self.create()['approval_token'], self.create()['approval_token'])

class SummaryTests(unittest.TestCase):
    def test_configuration_requires_all(self):
        with patch.dict(os.environ, {'AI_BASE_URL':'https://example.invalid', 'AI_API_KEY':'', 'AI_MODEL':''}, clear=True):
            with self.assertRaises(ValueError): configured_summarizer()
    def test_http_provider_uses_model_and_preserves_amount(self):
        response = io.BytesIO(json.dumps({'choices':[{'message':{'content':'Add an outlet.'}}]}).encode())
        with patch('urllib.request.urlopen', return_value=response) as call:
            result = HTTPSummarizer('https://example.invalid/v1/chat/completions', 'key', 'model').summarize({'note':'outlet', 'amount':'450.00'})
        self.assertIn('$450.00', result); self.assertIn('Add an outlet.', result)
        self.assertEqual(json.loads(call.call_args.args[0].data)['model'], 'model')

class WebTests(unittest.TestCase):
    def test_web_ui_upload_approval_invoice_and_webhook(self):
        import re
        from urllib.parse import urlencode
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            handler, orders, invoices = make_app(tmp); server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = 'http://127.0.0.1:%d' % server.server_address[1]
            try:
                with urllib.request.urlopen(base) as r: page = r.read().decode()
                csrf = re.search('name="csrf" value="([^"]+)', page).group(1)
                boundary = 'TESTBOUNDARY'; parts = []
                for key, value in {'csrf':csrf,'title':'Outlet','note':'Add outlet','amount':'450','homeowner':'Alex','email':'a@example.com'}.items():
                    parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+key+'"\r\n\r\n'+value+'\r\n').encode())
                parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="photo"; filename="test.png"\r\nContent-Type: image/png\r\n\r\n').encode()+b'\x89PNG\r\n\x1a\nphoto\r\n'); parts.append(('--'+boundary+'--\r\n').encode())
                req = urllib.request.Request(base+'/create', data=b''.join(parts), headers={'Content-Type':'multipart/form-data; boundary='+boundary})
                with urllib.request.urlopen(req) as r: self.assertIn('Outlet', r.read().decode())
                o = orders.all()[0]; self.assertTrue(os.path.exists(os.path.join(tmp,'uploads',o['photo'])))
                with urllib.request.urlopen(base+'/photo/'+o['approval_token']) as r: self.assertTrue(r.read().startswith(b'\x89PNG'))
                def post(path, fields):
                    with urllib.request.urlopen(base+path, data=urlencode(fields).encode()) as r: return r.read()
                post('/decide/'+o['approval_token'], {'csrf':csrf,'decision':'APPROVED'})
                post('/invoice/'+o['id'], {'csrf':csrf})
                o=orders.get(o['id']); event={'event_type':'INVOICING.INVOICE.PAID','resource':{'id':o['invoice_id'],'status':'PAID'}}
                req=urllib.request.Request(base+'/webhook', data=json.dumps(event).encode(), headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(req) as r: self.assertTrue(json.load(r)['marked_paid'])
                with urllib.request.urlopen(base) as r: self.assertIn('PAID', r.read().decode())
            finally: server.shutdown(); server.server_close(); thread.join()
    def test_live_requires_webhook_id(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError): make_app(tmp, mock=False)

if __name__ == '__main__': unittest.main()
