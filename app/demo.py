"""Run the complete local product flow without external services."""
import json
import tempfile
import threading
import urllib.request
from .summarizer import LocalSummarizer
from .web import make_app
from http.server import ThreadingHTTPServer


def main():
    print('Change-Order Collector demo (local summary, mock PayPal)')
    try:
        with tempfile.TemporaryDirectory(prefix='coc-demo-') as tmp:
            handler, orders, invoices = make_app(tmp, mock=True, summarizer=LocalSummarizer())
            order = orders.create('Extra kitchen outlet', 'Install one additional kitchen outlet.', '450.00', 'Taylor Homeowner', 'homeowner@example.com')
            assert orders.get(order['id'])
            print('PASS change order created')
            assert 'Install one additional' in order['summary'] and '$450.00' in order['summary']
            print('PASS local summary generated')
            try: orders.invoice(order['id'])
            except ValueError: pass
            else: raise AssertionError('Invoice allowed before approval')
            print('PASS invoice blocked before approval')
            order = orders.decide(order['approval_token'], 'APPROVED')
            assert order['decision_at'] and order['approval'] == 'APPROVED'
            print('PASS homeowner approval recorded')
            order = orders.invoice(order['id']); invoice_id = order['invoice_id']
            assert invoices.get_invoice(invoice_id)['status'] == 'SENT'
            print('PASS mock PayPal invoice created and sent')
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                body = json.dumps({'id': 'WH-DEMO', 'event_type': 'INVOICING.INVOICE.PAID', 'resource': {'id': invoice_id, 'status': 'PAID'}}).encode()
                req = urllib.request.Request('http://127.0.0.1:%d/webhook' % server.server_address[1], data=body, headers={'Content-Type': 'application/json'}, method='POST')
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=5) as response: result = json.load(response)
                assert result['marked_paid']
                print('PASS simulated paid webhook received')
                assert invoices.get_invoice(invoice_id)['status'] == 'PAID'
                print('PASS invoice reconciled as paid')
            finally:
                server.shutdown(); server.server_close(); thread.join()
        print('RESULT: PASS')
        return 0
    except Exception as exc:
        print('FAIL: %s' % exc); print('RESULT: FAIL'); return 1

if __name__ == '__main__': raise SystemExit(main())
