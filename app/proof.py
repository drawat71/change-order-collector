"""End-to-end proof CLI.

Mock mode (no credentials, no network beyond localhost):

    python3 -m app.proof --mock

Live sandbox mode (credentials in .env, see README.md):

    python3 -m app.proof

The proof runs, in order:
  1. OAuth token fetch
  2. Draft invoice creation
  3. Invoice send
  4. Webhook delivery (mock: a simulated INVOICING.INVOICE.PAID event
     is POSTed to the local webhook server; live: the step is reported
     as waiting, because the real event arrives asynchronously from
     PayPal after the invoice is paid in the sandbox)
  5. Invoice marked PAID in the local store (mock mode only)

Exit code is 0 only when every checked step passes.
Run as a script too: python3 -m app.proof --mock
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import urllib.request

# Allow `python3 app/proof.py` style runs as a fallback.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.paypal_client import PayPalClient, PayPalConfig, PayPalConfigError
    from app.store import InvoiceStore
    from app.webhook import run_server
else:
    from .paypal_client import PayPalClient, PayPalConfig, PayPalConfigError
    from .store import InvoiceStore
    from .webhook import run_server


def _post_json(url, payload):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def run_proof(mock=False, data_dir=None, billing_email="homeowner@example.com",
              item_name="Change order: extra outlet in kitchen",
              amount="450.00", currency="USD", verbose=False):
    """Run the proof flow. Returns (all_passed, results_dict)."""
    log = print if verbose else (lambda *args, **kwargs: None)
    results = {}

    if data_dir is None:
        if mock:
            data_dir = tempfile.mkdtemp(prefix="coc-proof-")
        else:
            data_dir = os.path.join(os.getcwd(), "data")
    os.makedirs(data_dir, exist_ok=True)
    store_path = os.path.join(data_dir, "store.json")
    events_path = os.path.join(data_dir, "events.jsonl")
    store = InvoiceStore(store_path)

    config = PayPalConfig(mock=mock)
    client = PayPalClient(config=config)

    # 1. Token
    try:
        token = client.get_access_token()
        results["token"] = bool(token)
    except Exception as exc:  # PayPalConfigError or API error
        print("token error: %s" % exc)
        results["token"] = False
        return False, results

    # 2. Create invoice
    invoice_id = None
    try:
        created = client.create_invoice(
            billing_email=billing_email,
            item_name=item_name,
            amount=amount,
            currency=currency,
            note="Change-Order Collector sandbox proof invoice.",
        )
        invoice_id = created.get("id")
        results["invoice_created"] = bool(invoice_id)
        if invoice_id:
            store.add_invoice(invoice_id, {"status": created.get("status", "DRAFT")})
    except Exception as exc:
        print("invoice create error: %s" % exc)
        results["invoice_created"] = False
        return False, results

    # 3. Send invoice
    try:
        sent = client.send_invoice(invoice_id)
        results["invoice_sent"] = sent is not None
        if invoice_id:
            store.set_status(invoice_id, "SENT")
    except Exception as exc:
        print("invoice send error: %s" % exc)
        results["invoice_sent"] = False
        return False, results

    # 4 and 5. Webhook, mock mode only (live events are asynchronous).
    if not mock:
        print("Live mode: invoice %s created and sent in the sandbox." % invoice_id)
        print("Live mode: pay the invoice in the PayPal sandbox, then run the")
        print("webhook server and check data/store.json for status PAID:")
        print("  python3 -m app.webhook_server")
        results["webhook_received"] = None  # not checkable synchronously
        results["invoice_marked_paid"] = None
        all_passed = all(v for v in results.values() if v is not None)
        results["invoice_id"] = invoice_id
        return all_passed, results

    server = run_server("127.0.0.1", 0, store, events_path, client=client, log=log)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        simulated_event = {
            "id": "WH-MOCK-0001",
            "event_type": "INVOICING.INVOICE.PAID",
            "resource_type": "invoice",
            "resource": {
                "id": invoice_id,
                "status": "PAID",
                "detail": {"currency_code": currency},
            },
        }
        response = _post_json(
            "http://127.0.0.1:%d/webhook" % port, simulated_event
        )
        results["webhook_received"] = bool(
            response and response.get("event_type") == "INVOICING.INVOICE.PAID"
        )
        record = store.get_invoice(invoice_id)
        results["invoice_marked_paid"] = bool(
            record and record.get("status") == "PAID"
        )
    except Exception as exc:
        print("webhook error: %s" % exc)
        results["webhook_received"] = False
        results["invoice_marked_paid"] = False
    finally:
        server.shutdown()
        server.server_close()

    results["invoice_id"] = invoice_id
    results["data_dir"] = data_dir
    all_passed = all(
        results.get(key) for key in (
            "token", "invoice_created", "invoice_sent",
            "webhook_received", "invoice_marked_paid",
        )
    )
    return all_passed, results


def main(argv=None):
    parser = argparse.ArgumentParser(description="Change-Order Collector proof")
    parser.add_argument("--mock", action="store_true",
                        help="Run in mock mode (no credentials, no PayPal network calls)")
    parser.add_argument("--data-dir", default=None,
                        help="Where to put store.json and events.jsonl")
    parser.add_argument("--currency", default="USD", choices=("USD", "CAD"))
    parser.add_argument("--billing-email", default="homeowner@example.com")
    parser.add_argument("--amount", default="450.00")
    args = parser.parse_args(argv)

    mock = args.mock or os.environ.get("PAYPAL_MOCK", "") in ("1", "true", "TRUE")

    if not mock:
        # Fail fast with the helpful message instead of a stack trace.
        try:
            PayPalConfig().require_credentials()
        except PayPalConfigError as exc:
            print("FAIL token: %s" % exc)
            return 2

    print("Change-Order Collector proof (%s mode)" % ("mock" if mock else "live sandbox"))
    all_passed, results = run_proof(
        mock=mock, data_dir=args.data_dir,
        billing_email=args.billing_email, amount=args.amount,
        currency=args.currency, verbose=False,
    )

    def line(label, key):
        value = results.get(key)
        if value is None:
            print("SKIP %s (arrives asynchronously in live mode)" % label)
        else:
            print("%s %s" % ("PASS" if value else "FAIL", label))

    line("token", "token")
    line("invoice created", "invoice_created")
    if results.get("invoice_id"):
        print("     invoice_id=%s" % results["invoice_id"])
    line("invoice sent", "invoice_sent")
    line("webhook received", "webhook_received")
    line("invoice marked paid", "invoice_marked_paid")
    print("RESULT: %s" % ("PASS" if all_passed else "FAIL"))
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
