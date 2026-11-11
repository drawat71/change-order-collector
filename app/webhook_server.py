"""Standalone webhook server entry point.

    python3 -m app.webhook_server [--port 8000] [--data-dir data]

Listens for PayPal webhooks on POST /webhook and updates the local
store in <data-dir>/store.json, appending raw events to
<data-dir>/events.jsonl. Point a tunnel (for example a localhost
tunnel with a public HTTPS URL) at this server for the live sandbox
demo, and register that URL in the PayPal developer dashboard.
"""

from __future__ import annotations

import argparse
import os

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.paypal_client import PayPalClient, PayPalConfig
    from app.store import InvoiceStore
    from app.webhook import run_server
else:
    from .paypal_client import PayPalClient, PayPalConfig
    from .store import InvoiceStore
    from .webhook import run_server


def main(argv=None):
    parser = argparse.ArgumentParser(description="Change-Order Collector webhook server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args(argv)

    os.makedirs(args.data_dir, exist_ok=True)
    store = InvoiceStore(os.path.join(args.data_dir, "store.json"))
    events_path = os.path.join(args.data_dir, "events.jsonl")
    # The client is only used for webhook signature verification. In
    # mock mode it never calls the network for verification.
    client = PayPalClient(config=PayPalConfig())
    server = run_server(args.host, args.port, store, events_path, client=client)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
