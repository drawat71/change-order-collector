# Change-Order Collector

Change orders are where contractor jobs leak money and trust: they are often agreed verbally and disputed later. Change-Order Collector lets a contractor log a change order with a photo and a short note. The app produces a clean client-facing summary with the amount, and the homeowner approves or declines through a unique link. Approval, and only approval, triggers a real PayPal invoice. PayPal webhooks reconcile the invoice as paid.

## How PayPal is used

The app uses OAuth client credentials and the PayPal Invoicing API in the sandbox to create a draft invoice and send it. It receives `INVOICING.INVOICE.PAID` webhooks to reconcile payment. Invoicing is gated on homeowner approval in code and covered by tests.

## AI tools

The app was built with AI coding assistance from OpenAI Codex. The default summarizer is deterministic and local. An optional adapter calls an OpenAI-compatible model endpoint. The recorded demo configuration used a local `qwen3:8b` model via Ollama to produce a faithful summary; the app appends the amount itself, and the model is instructed never to invent facts.

## How to run

Requires Python 3.10+ and only the standard library. For the mock demo, no credentials are needed:

```bash
git clone https://github.com/drawat71/change-order-collector.git
cd change-order-collector
python3 -m app.demo
```

To explore the interface in mock mode, run `python3 -m app.web` and open http://127.0.0.1:8000. For live sandbox invoicing, copy `.env.example` to `.env`, configure the sandbox values including `PAYPAL_WEBHOOK_ID`, enable Invoicing for the PayPal app, and run `python3 -m app.web --live-paypal`. Configure and test webhook verification separately; do not use production credentials or expose this prototype as a public service. See the README for details and limitations.

Demo video: <to be added>

Repository: https://github.com/drawat71/change-order-collector
