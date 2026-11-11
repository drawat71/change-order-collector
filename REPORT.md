# Build report

## Built

A standard-library local web app captures change orders and optional locally saved JPEG/PNG photos, prepares a client-facing summary, records a one-time homeowner approval or decline with a UTC timestamp, gates invoicing on approval, and displays webhook-reconciled invoice status. The existing PayPal client and webhook store remain in use. The offline CLI runs the entire workflow in a temporary directory. An optional OpenAI-compatible HTTP adapter is available but was not contacted. The shipped demo uses the deterministic local summary, not generative AI. `REVIEW.md` records the pre-build critique.

Design choices for a short demo: USD and due-on-receipt terms are fixed; the draft is generated immediately on creation; the homeowner link is opened from the dashboard instead of sent by email; mock PayPal is the web default. A photo is optional and is displayed as evidence, not interpreted. The CLI simulates paid status over localhost rather than adding a payment simulation button to the interface.

## Exact verification output

`python3 -m app.demo`:

```text
Change-Order Collector demo (local summary, mock PayPal)
PASS change order created
PASS local summary generated
PASS invoice blocked before approval
PASS homeowner approval recorded
PASS mock PayPal invoice created and sent
PASS simulated paid webhook received
PASS invoice reconciled as paid
RESULT: PASS
```

`python3 -m app.proof --mock`:

```text
Change-Order Collector proof (mock mode)
PASS token
PASS invoice created
     invoice_id=INV-MOCK-0001
PASS invoice sent
PASS webhook received
PASS invoice marked paid
RESULT: PASS
```

`python3 -m unittest discover -s tests -v`:

```text
test_invoice_payload_shape (test_mock_flow.MockClientTests.test_invoice_payload_shape) ... ok
test_missing_credentials_raise_helpful_error (test_mock_flow.MockClientTests.test_missing_credentials_raise_helpful_error) ... ok
test_mock_create_and_send_invoice (test_mock_flow.MockClientTests.test_mock_create_and_send_invoice) ... ok
test_mock_token (test_mock_flow.MockClientTests.test_mock_token) ... ok
test_mock_proof_end_to_end (test_mock_flow.ProofTests.test_mock_proof_end_to_end) ... ok
test_approval_gate_and_one_invoice (test_orders.OrderTests.test_approval_gate_and_one_invoice) ... ok
test_decline_is_final_and_blocks_invoice (test_orders.OrderTests.test_decline_is_final_and_blocks_invoice) ... ok
test_send_failure_preserves_draft (test_orders.OrderTests.test_send_failure_preserves_draft) ... ok
test_sent_does_not_overwrite_paid (test_orders.OrderTests.test_sent_does_not_overwrite_paid) ... ok
test_summary_and_persistence (test_orders.OrderTests.test_summary_and_persistence) ... ok
test_tokens_are_unique (test_orders.OrderTests.test_tokens_are_unique) ... ok
test_validation (test_orders.OrderTests.test_validation) ... ok
test_configuration_requires_all (test_orders.SummaryTests.test_configuration_requires_all) ... ok
test_http_provider_uses_model_and_preserves_amount (test_orders.SummaryTests.test_http_provider_uses_model_and_preserves_amount) ... ok
test_live_requires_webhook_id (test_orders.WebTests.test_live_requires_webhook_id) ... ok
test_web_ui_upload_approval_invoice_and_webhook (test_orders.WebTests.test_web_ui_upload_approval_invoice_and_webhook) ... ok
test_post_webhook_over_http (test_webhook.HttpWebhookTests.test_post_webhook_over_http) ... ok
test_capture_completed_with_invoice_id_marks_paid (test_webhook.ProcessEventTests.test_capture_completed_with_invoice_id_marks_paid) ... ok
test_capture_completed_without_invoice_id_is_graceful (test_webhook.ProcessEventTests.test_capture_completed_without_invoice_id_is_graceful) ... ok
test_invoice_paid_marks_paid (test_webhook.ProcessEventTests.test_invoice_paid_marks_paid) ... ok
test_unrelated_event_does_not_mark_paid (test_webhook.ProcessEventTests.test_unrelated_event_does_not_mark_paid) ... ok

----------------------------------------------------------------------
Ran 21 tests in 1.611s

OK
```

## Remaining risks and next steps

- This is not ready for real customer data or public deployment. There is no contractor authentication, verified homeowner identity, link expiration, production-grade audit record, or secure multi-user storage. Bearer links can be forwarded. Data and images are plaintext locally.
- Mock webhooks are unsigned. The standalone scaffold fails open without a webhook ID; the web app requires one outside mock mode. Validate signature rejection, PayPal payloads, invoice delivery and a real sandbox payment before a live claim. Handle verification failures and outages operationally. No external service was contacted in this work.
- The JSON stores are single-process, not transactional across files or PayPal; process crashes or ambiguous API responses can orphan or duplicate remote invoices. A failed send leaves a draft and requires manual reconciliation. Event replay, unknown invoice IDs, refunds and state changes need deliberate handling. Photo type checks are shallow and uploads need stronger validation and retention controls.
- The deterministic summary does not demonstrate generative AI. Test the optional provider with consented sample data, check for invented scope, enable contractor review/editing, and measure output quality before competing on PayPal + AI. Photos are not analyzed. The public repository, final AI disclosure, Devpost entry, and video remain to be made.
- This transferred directory has no Git metadata. No push or external service call was made.

## Recommended video outline (under 3 minutes)

- **0:00–0:20 — Hook:** show the friction: a contractor finishes extra work and later has to reconstruct what the homeowner agreed to. State the promise: approval before an invoice.
- **0:20–0:55 — Capture:** create a concrete extra-outlet change, attach a photo, enter $450, and show the generated scope and terms. Say clearly that the shown local draft is deterministic; do not imply photo analysis.
- **0:55–1:25 — Consent:** open the homeowner link, read the scope and amount, approve, and show the timestamp and status on the dashboard. Mention that the link is a prototype bearer link, not identity verification.
- **1:25–1:55 — PayPal:** create the invoice from the approved record and show SENT. Explain that the same approved data feeds PayPal invoicing; label this run mock. If a verified sandbox is ready, substitute a real sandbox send and payment and identify it accurately.
- **1:55–2:20 — Close the loop:** run `python3 -m app.demo` and point to the simulated paid webhook and reconciled PAID line. Explain the webhook updates the dashboard in a real integrated run; do not suggest the CLI sample is the same persisted UI order.
- **2:20–2:45 — Why it matters and credibility:** recap the evidence → approval → invoice → paid trail, state the remaining sandbox and AI verification work, and end on the reproducible command and repository link. Leave a few seconds of margin for pacing and a clear final frame.
