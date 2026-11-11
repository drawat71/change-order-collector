"""Local demo UI and PayPal webhook endpoint."""
import argparse
import html
import json
import os
import secrets
from email.parser import BytesParser
from email.policy import default
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .orders import Orders
from .paypal_client import PayPalClient, PayPalConfig
from .store import InvoiceStore
from .summarizer import configured_summarizer
from .webhook import make_handler


def esc(value):
    return html.escape(str(value), quote=True)


def make_app(data_dir, mock=True, summarizer=None):
    os.makedirs(data_dir, exist_ok=True)
    config = PayPalConfig(mock=mock)
    if not config.mock and not config.webhook_id:
        raise ValueError('PAYPAL_WEBHOOK_ID is required for the web app outside mock mode.')
    client = PayPalClient(config=config)
    invoices = InvoiceStore(os.path.join(data_dir, 'store.json'))
    orders = Orders(os.path.join(data_dir, 'orders.json'), invoices, client, summarizer or configured_summarizer())
    csrf = secrets.token_urlsafe(32)
    parent = make_handler(invoices, os.path.join(data_dir, 'events.jsonl'), client=client, log=lambda *a: None)

    class Handler(parent):
        def page(self, content, status=200):
            body = ('''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Change-Order Collector</title><style>
            body{font:16px system-ui;background:#f4f6f7;color:#182630;margin:0} main{max-width:900px;margin:auto;padding:32px 20px} h1{font-size:2rem} h2{margin-top:0} .card{background:white;padding:24px;border-radius:12px;margin:18px 0;box-shadow:0 2px 12px #162a3810} label{display:block;font-weight:600;margin:12px 0 5px} input,textarea{box-sizing:border-box;width:100%;padding:10px;border:1px solid #b4c3c8;border-radius:6px;font:inherit} textarea{min-height:90px} button,.button{display:inline-block;background:#0070ba;color:white;border:0;padding:11px 17px;border-radius:6px;font-weight:700;cursor:pointer;text-decoration:none} .secondary{background:#455a64} .meta{color:#536b73} .summary{white-space:pre-wrap;line-height:1.6} a{color:#006eaa} .tag{font-weight:700;color:#126b52} .row{display:flex;gap:10px;flex-wrap:wrap} .row form{display:inline} img{max-width:100%;max-height:300px} </style></head><body><main>''' + content + '</main></body></html>').encode()
            self.send_response(status); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.send_header('Content-Length', str(len(body))); self.send_header('Cache-Control', 'no-store'); self.send_header('Referrer-Policy', 'no-referrer'); self.end_headers(); self.wfile.write(body)

        def redirect(self, path):
            self.send_response(303); self.send_header('Location', path); self.end_headers()

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == '/':
                cards = ''
                for o in reversed(orders.all()):
                    inv = invoices.get_invoice(o['invoice_id']) if o['invoice_id'] else None
                    status = inv['status'] if inv else 'NOT CREATED'
                    action = (f'<form method="post" action="/invoice/{esc(o["id"])}"><input type="hidden" name="csrf" value="{csrf}"><button>Create &amp; send invoice</button></form>' if o['approval'] == 'APPROVED' and not o['invoice_id'] else '')
                    cards += f'''<section class="card"><h2>{esc(o['title'])} · ${esc(o['amount'])}</h2><p>{esc(o['homeowner'])} · {esc(o['email'])}</p><p class="summary">{esc(o['summary'])}</p><p>Approval: <span class="tag">{esc(o['approval'])}</span> {esc(o['decision_at'] or '')} · Invoice: <span class="tag">{esc(status)}</span></p><div class="row"><a class="button secondary" href="/approve/{esc(o['approval_token'])}">Open homeowner link</a>{action}</div></section>'''
                self.page('''<h1>Change-Order Collector</h1><p class="meta">Document the change. Get approval. Collect with PayPal.</p><section class="card"><h2>New change order</h2><form method="post" action="/create" enctype="multipart/form-data">''' + f'<input type="hidden" name="csrf" value="{csrf}">' + '''<label>Title</label><input name="title" required maxlength="120"><label>Contractor note</label><textarea name="note" required maxlength="4000"></textarea><label>Amount (USD)</label><input name="amount" type="number" min="0.01" step="0.01" required><label>Homeowner name</label><input name="homeowner" required><label>Homeowner email</label><input name="email" type="email" required><label>Photo (optional, JPEG or PNG, max 5 MB)</label><input name="photo" type="file" accept="image/jpeg,image/png"><p><button>Draft change order</button></p></form></section><h2>Change orders</h2>''' + (cards or '<p>No change orders yet.</p>'))
            elif path.startswith('/approve/'):
                token = path[len('/approve/'):]; o = orders.by_token(token)
                if not o: return self.page('<h1>Link not found</h1>', 404)
                photo = f'<p><img src="/photo/{esc(token)}" alt="Change order photo"></p>' if o['photo'] else ''
                actions = f'''<div class="row"><form method="post" action="/decide/{esc(token)}"><input type="hidden" name="csrf" value="{csrf}"><button name="decision" value="APPROVED">Approve ${esc(o['amount'])}</button></form><form method="post" action="/decide/{esc(token)}"><input type="hidden" name="csrf" value="{csrf}"><button class="secondary" name="decision" value="DECLINED">Decline</button></form></div>''' if o['approval'] == 'PENDING' else f'<p class="tag">{esc(o["approval"])} · {esc(o["decision_at"])}</p>'
                self.page(f'<h1>Review your change order</h1><section class="card"><h2>{esc(o["title"])}</h2><p>Prepared for {esc(o["homeowner"])}</p><p class="summary">{esc(o["summary"])}</p>{photo}{actions}</section>')
            elif path.startswith('/photo/'):
                o = orders.by_token(path[len('/photo/'):])
                if not o or not o['photo']: return self.page('Not found', 404)
                with open(os.path.join(data_dir, 'uploads', o['photo']), 'rb') as f: body = f.read()
                self.send_response(200); self.send_header('Content-Type', 'image/png' if o['photo'].endswith('.png') else 'image/jpeg'); self.send_header('Content-Length', str(len(body))); self.send_header('X-Content-Type-Options', 'nosniff'); self.end_headers(); self.wfile.write(body)
            else: self.page('Not found', 404)

        def do_POST(self):
            path = urlsplit(self.path).path
            if path == '/webhook': return super().do_POST()
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 6 * 1024 * 1024: raise ValueError('Request is empty or too large.')
                raw = self.rfile.read(length); content_type = self.headers.get('Content-Type', '')
                fields = {}; photo = None
                if content_type.startswith('multipart/form-data'):
                    msg = BytesParser(policy=default).parsebytes(('Content-Type: ' + content_type + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + raw)
                    if not msg.is_multipart(): raise ValueError('Invalid upload.')
                    for part in msg.iter_parts():
                        name = part.get_param('name', header='content-disposition'); value = part.get_payload(decode=True)
                        if name == 'photo' and part.get_filename(): photo = value
                        elif name: fields[name] = value.decode('utf-8')
                else:
                    fields = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
                if not secrets.compare_digest(fields.get('csrf', ''), csrf): raise ValueError('Invalid form token.')
                if path == '/create':
                    filename = None
                    if photo:
                        if len(photo) > 5 * 1024 * 1024: raise ValueError('Photo exceeds 5 MB.')
                        ext = '.png' if photo.startswith(b'\x89PNG\r\n\x1a\n') else '.jpg' if photo.startswith(b'\xff\xd8\xff') else None
                        if not ext: raise ValueError('Photo must be JPEG or PNG.')
                        filename = secrets.token_hex(20) + ext
                    o = orders.create(*(fields.get(k, '') for k in ('title', 'note', 'amount', 'homeowner', 'email')), photo=filename)
                    if filename:
                        os.makedirs(os.path.join(data_dir, 'uploads'), exist_ok=True)
                        with open(os.path.join(data_dir, 'uploads', filename), 'wb') as f: f.write(photo)
                    self.redirect('/')
                elif path.startswith('/decide/'):
                    orders.decide(path[len('/decide/'):], fields.get('decision')); self.redirect('/approve/' + path[len('/decide/'):])
                elif path.startswith('/invoice/'):
                    orders.invoice(path[len('/invoice/'):]); self.redirect('/')
                else: self.page('Not found', 404)
            except Exception as exc:
                self.page(f'<h1>Could not complete action</h1><p>{esc(exc)}</p><p><a href="/">Back to dashboard</a></p>', 400)
    return Handler, orders, invoices


def main():
    parser = argparse.ArgumentParser(description='Local Change-Order Collector')
    parser.add_argument('--port', type=int, default=8000); parser.add_argument('--data-dir', default='data')
    parser.add_argument('--live-paypal', action='store_true', help='Use configured PayPal instead of local mock')
    args = parser.parse_args()
    handler, _, _ = make_app(args.data_dir, mock=not args.live_paypal)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler)
    print(f'Open http://127.0.0.1:{server.server_address[1]} (PayPal {"live configuration" if args.live_paypal else "mock"})', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__ == '__main__': main()
