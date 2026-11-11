# Change-Order Collector

A local prototype for documenting contractor change orders, getting homeowner approval, and issuing a PayPal invoice from the approved record. The dashboard shows approval and payment status; a PayPal paid webhook updates the invoice store.

Python 3.10+; standard library only. No install, credentials, accounts, or external services are needed for the mock demo. MIT licensed.

## Judge quick start

After the repository is published, clone it and enter its directory:

```bash
git clone <public-repository-url>
cd change-order-collector
python3 -m app.demo
```

The command creates a sample order in a temporary directory, generates a local summary, proves invoicing is blocked before approval, records approval, creates and sends a **mock** PayPal invoice, and posts a simulated paid webhook to a localhost server. It prints PASS for each step and exits 0 only on success. No files or data from the demo persist.

To explore the interface:

```bash
python3 -m app.web
```

Open http://127.0.0.1:8000. Create a change order with a note, USD amount, homeowner details, and optionally a JPEG or PNG photo. Open the homeowner link shown on the dashboard, approve or decline, then return to the dashboard and create the invoice after approval. Mock mode simulates invoice creation and sending; no email or payment is sent. The CLI demo simulates the paid webhook; the web UI itself does not provide a paid simulation button. Local data and uploads are in `data/`. Stop with Ctrl-C. The server listens only on localhost.

```bash
python3 -m unittest discover -s tests -v
python3 -m app.proof --mock
```

The second command preserves the original independent PayPal plumbing proof. The application uses no external services by default; unset any `AI_*` variables to ensure the interactive app also uses the local summarizer. The CLI demo always uses the local summarizer regardless of those variables.

## Architecture and choices

- `app/web.py`: local contractor dashboard, photo upload, bearer-link homeowner decision, invoice action, and `/webhook` endpoint.
- `app/orders.py`: local change order records, immutable decision with UTC timestamp, approval gate and invoice creation. The approved title, recipient, amount and summary are passed to the PayPal client. A draft ID is saved before sending to avoid blindly creating another invoice after a send error.
- `app/summarizer.py`: deterministic local summary by default; optional OpenAI-compatible chat completions HTTP adapter. The note supplies the scope; amount and due-on-receipt terms are added by the application. Photos are evidence for the homeowner, not analyzed by the summary provider. Review the draft before approving; it is not independently verified.
- `app/paypal_client.py`, `app/store.py`, `app/webhook.py`: PayPal OAuth/invoicing and signature-verification API, JSON invoice store, and paid-event reconciliation. Mock mode performs no PayPal calls.
- `app/demo.py` and `app/proof.py`: repeatable local end-to-end and original payment plumbing proofs, respectively.

Decision links are high-entropy bearer secrets and can be opened by anyone holding them. The dashboard does not send links or authenticate users. This is a single-process, local prototype: do not expose it publicly or use real customer data. Files are local plaintext. There is no identity verification, expiry, robust audit trail, multi-process database, comprehensive upload inspection, or production retry/idempotency strategy. A send failure leaves a draft recorded and requires manual reconciliation. A paid webhook may create an unknown invoice record; event replay and unexpected payment states need hardening. The standalone scaffold webhook skips verification without a webhook ID, so never expose it in that configuration. The web app requires `PAYPAL_WEBHOOK_ID` in non-mock mode. Live webhook delivery is exercised at demo time.

## Optional integrations

The interactive app defaults to mock PayPal. `python3 -m app.web --live-paypal` uses the existing PayPal configuration, requires `PAYPAL_WEBHOOK_ID`, and can contact PayPal and send an invoice. It is intentionally not part of the judge quick start. Before any sandbox demonstration, configure and test sandbox credentials and webhook verification separately; do not use production credentials or expose this prototype as a public service. See `.env.example` for existing PayPal variable names. The scaffold reads `.env` at startup. The PayPal app must have the Invoicing feature enabled.

On November 11, 2026, the live sandbox proof passed against https://api-m.sandbox.paypal.com: OAuth token fetch, draft invoice creation, and invoice send all succeeded. The recorded example was invoice `INV2-HTBN-5FEL-9XNE-APE3`, USD 450.00, status `SENT`. The proof required a fix to parse the invoice ID from the create response `href`.

In live mode, the paid leg completes asynchronously: `INVOICING.INVOICE.PAID` fires only after a sandbox buyer pays the invoice. The webhook receiver and paid reconciliation are proven end to end by the mock proof and test suite; live webhook delivery is exercised at demo time.

To select the optional model-backed summarizer, set all three environment variables before starting the interactive app: `AI_BASE_URL` (the OpenAI-compatible API base ending in `/v1`), `AI_API_KEY`, and `AI_MODEL`. The adapter POSTs the contractor note to `AI_BASE_URL/chat/completions`; this sends the note to the configured provider and requires network access. Partial configuration fails at startup. The recorded demo configuration used a local `qwen3:8b` model via Ollama. Keep keys out of source control. The deterministic default and CLI demo use no AI model or API key.

## Draft Devpost description

**Problem.** Extra work often starts as a quick conversation or photo. When scope and price are not recorded before billing, contractors spend time reconstructing the agreement and homeowners face a surprise invoice.

**How it works.** The contractor logs the change, price, homeowner, and photo. A summary step prepares a client-facing scope, amount and terms. The homeowner opens a unique link and approves or declines. Only an approved record can create an invoice. PayPal invoicing carries the approved amount to the recipient; a paid webhook updates the dashboard so the approval-to-payment trail is visible.

**Why PayPal is central.** The invoice is the handoff from an approved change to collection, and the webhook closes the loop. The runnable offline demo simulates both PayPal invoice operations and the paid event; it is not evidence of a real payment. The live sandbox proof covered invoice creation and sending; the paid leg awaits a sandbox buyer payment and live webhook delivery is exercised at demo time.

**AI tools statement.** The included judge demo uses a deterministic, rule-based summary and does not call a generative AI model; it does not interpret photos. The app was built with OpenAI Codex. An optional OpenAI-compatible adapter was exercised in the recorded demo configuration using a local `qwen3:8b` model via Ollama; it is instructed never to invent facts, and the app appends the amount itself.

## License

[MIT](LICENSE). The transferred workspace did not include Git metadata; a public repository and submission are still to be created separately.
