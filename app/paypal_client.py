"""PayPal invoicing client.

Standard library only (urllib, base64, json).

Real mode talks to the PayPal REST API:
  - OAuth:  POST /v1/oauth2/token (client credentials)
  - Create: POST /v2/invoicing/invoices
  - Send:   POST /v2/invoicing/invoices/{id}/send

Mock mode (PAYPAL_MOCK=1 or mock=True) simulates all three calls
locally, needs no credentials, and never touches the network.
"""

from __future__ import annotations

import base64
import datetime
import json
import os
import urllib.error
import urllib.request
import urllib.parse
import uuid

SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"
LIVE_BASE_URL = "https://api-m.paypal.com"

MISSING_CREDENTIALS_MESSAGE = (
    "PayPal credentials are missing. Copy .env.example to .env, then set "
    "PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET from your Sandbox app at "
    "developer.paypal.com. See the 'Live sandbox setup' section of "
    "README.md for the exact steps. To run without credentials, use mock "
    "mode: python3 -m app.proof --mock"
)


class PayPalConfigError(RuntimeError):
    """Raised when required PayPal configuration is missing."""


class PayPalAPIError(RuntimeError):
    """Raised when a PayPal API call fails."""


def _load_dotenv(path=".env"):
    """Minimal .env loader: sets variables that are not already set."""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


def is_mock_enabled(mock=None):
    if mock is not None:
        return bool(mock)
    return os.environ.get("PAYPAL_MOCK", "").strip() in ("1", "true", "TRUE", "yes")


class PayPalConfig:
    def __init__(self, client_id=None, client_secret=None, env=None,
                 webhook_id=None, mock=None, load_env_file=True):
        if load_env_file:
            _load_dotenv()
        self.client_id = client_id or os.environ.get("PAYPAL_CLIENT_ID", "")
        self.client_secret = (
            client_secret or os.environ.get("PAYPAL_CLIENT_SECRET", "")
        )
        self.env = (env or os.environ.get("PAYPAL_ENV", "sandbox")).strip().lower()
        self.webhook_id = webhook_id or os.environ.get("PAYPAL_WEBHOOK_ID", "")
        self.mock = is_mock_enabled(mock)
        if self.env == "live":
            self.base_url = LIVE_BASE_URL
        else:
            self.env = "sandbox"
            self.base_url = SANDBOX_BASE_URL

    def require_credentials(self):
        if self.mock:
            return
        if not self.client_id or not self.client_secret:
            raise PayPalConfigError(MISSING_CREDENTIALS_MESSAGE)


def build_invoice_payload(billing_email, item_name="Change order",
                          amount="100.00", quantity="1", currency="USD",
                          invoicer_email=None, invoice_number=None,
                          note=None):
    """Build a /v2/invoicing/invoices request body."""
    today = datetime.date.today().isoformat()
    detail = {
        "invoice_number": invoice_number or ("CO-" + uuid.uuid4().hex[:10].upper()),
        "invoice_date": today,
        "currency_code": currency,
        "payment_term": {"term_type": "DUE_ON_RECEIPT"},
    }
    if note:
        detail["note"] = note
    invoicer = {}
    if invoicer_email:
        invoicer["email_address"] = invoicer_email
    payload = {
        "detail": detail,
        "invoicer": invoicer,
        "primary_recipients": [
            {
                "billing_info": {
                    "email_address": billing_email,
                }
            }
        ],
        "items": [
            {
                "name": item_name,
                "quantity": str(quantity),
                "unit_amount": {
                    "currency_code": currency,
                    "value": str(amount),
                },
            }
        ],
        "configuration": {
            "partial_payment": {"allow_partial_payment": False},
        },
    }
    return payload


class PayPalClient:
    """Thin PayPal invoicing client with a built-in mock transport."""

    def __init__(self, config=None, mock=None):
        self.config = config or PayPalConfig(mock=mock)
        self._access_token = None
        self._mock_counter = 0

    # -- transport -----------------------------------------------------
    def _request(self, method, path, body=None, headers=None, form=None):
        url = self.config.base_url + path
        data = None
        request_headers = {"Accept": "application/json"}
        if form is not None:
            data = form.encode("utf-8")
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(url, data=data, headers=request_headers,
                                         method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise PayPalAPIError(
                "PayPal API %s %s failed with HTTP %s: %s"
                % (method, path, exc.code, detail)
            ) from exc
        except urllib.error.URLError as exc:
            raise PayPalAPIError(
                "PayPal API %s %s could not be reached: %s" % (method, path, exc)
            ) from exc

    def _auth_headers(self):
        if not self._access_token:
            self.get_access_token()
        return {"Authorization": "Bearer " + self._access_token}

    # -- API -----------------------------------------------------------
    def get_access_token(self):
        """Fetch an OAuth client-credentials access token."""
        if self.config.mock:
            self._access_token = "MOCK-ACCESS-TOKEN"
            return self._access_token
        self.config.require_credentials()
        credentials = "%s:%s" % (self.config.client_id, self.config.client_secret)
        basic = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        result = self._request(
            "POST",
            "/v1/oauth2/token",
            headers={"Authorization": "Basic " + basic},
            form="grant_type=client_credentials",
        )
        token = result.get("access_token")
        if not token:
            raise PayPalAPIError("PayPal OAuth response had no access_token.")
        self._access_token = token
        return token

    def create_invoice(self, billing_email, item_name="Change order",
                       amount="100.00", quantity="1", currency="USD",
                       invoicer_email=None, note=None):
        """Create a draft invoice. Returns the parsed API response."""
        payload = build_invoice_payload(
            billing_email=billing_email,
            item_name=item_name,
            amount=amount,
            quantity=quantity,
            currency=currency,
            invoicer_email=invoicer_email
            or os.environ.get("PAYPAL_INVOICER_EMAIL") or None,
            note=note,
        )
        if self.config.mock:
            self._mock_counter += 1
            invoice_id = "INV-MOCK-%04d" % self._mock_counter
            # Prefer a deterministic id on the first mock invoice so the
            # proof output is stable and easy to read.
            if self._mock_counter == 1:
                invoice_id = "INV-MOCK-0001"
            return {
                "id": invoice_id,
                "status": "DRAFT",
                "href": "https://api-m.sandbox.paypal.com/v2/invoicing/invoices/"
                        + invoice_id,
                "detail": payload["detail"],
                "primary_recipients": payload["primary_recipients"],
                "items": payload["items"],
                "_mock_payload": payload,
            }
        self.config.require_credentials()
        result = self._request(
            "POST", "/v2/invoicing/invoices",
            body=payload, headers=self._auth_headers(),
        )
        href = result.get("href")
        if not href:
            href = next((link.get("href") for link in result.get("links", [])
                         if link.get("rel") == "self" and link.get("href")), None)
            if href:
                result["href"] = href
        if "id" not in result and href:
            result["id"] = urllib.parse.urlsplit(href).path.rstrip("/").rsplit("/", 1)[-1]
        return result

    def send_invoice(self, invoice_id, send_to_invoicer=True):
        """Send a previously created draft invoice."""
        if self.config.mock:
            return {"id": invoice_id, "status": "SENT", "_mock": True}
        self.config.require_credentials()
        body = {
            "send_to_invoicer": bool(send_to_invoicer),
            "send_to_recipient": True,
        }
        return self._request(
            "POST", "/v2/invoicing/invoices/%s/send" % invoice_id,
            body=body, headers=self._auth_headers(),
        )

    def verify_webhook_signature(self, headers, raw_body):
        """Verify a webhook signature via PayPal.

        Stub behaviour for the scaffold:
        - If PAYPAL_WEBHOOK_ID is not set, verification is skipped and
          (True, 'skipped...') is returned. This is development only.
        - If it is set, a real call is made to
          POST /v1/notifications/verify-webhook-signature and the result
          of that call is returned. Signature verification MUST be
          enabled for the live demo (see README.md).
        """
        webhook_id = self.config.webhook_id
        if not webhook_id:
            return True, "skipped: PAYPAL_WEBHOOK_ID is not set (development only)"
        if self.config.mock:
            return True, "mock: signature verification simulated"
        try:
            event = json.loads(raw_body.decode("utf-8")
                               if isinstance(raw_body, (bytes, bytearray))
                               else raw_body)
        except ValueError:
            return False, "webhook body was not valid JSON"
        body = {
            "transmission_id": headers.get("Paypal-Transmission-Id")
                                 or headers.get("paypal-transmission-id", ""),
            "transmission_time": headers.get("Paypal-Transmission-Time")
                                   or headers.get("paypal-transmission-time", ""),
            "cert_url": headers.get("Paypal-Cert-Url")
                        or headers.get("paypal-cert-url", ""),
            "auth_algo": headers.get("Paypal-Auth-Algo")
                         or headers.get("paypal-auth-algo", ""),
            "transmission_sig": headers.get("Paypal-Transmission-Sig")
                                or headers.get("paypal-transmission-sig", ""),
            "webhook_id": webhook_id,
            "webhook_event": event,
        }
        result = self._request(
            "POST", "/v1/notifications/verify-webhook-signature",
            body=body, headers=self._auth_headers(),
        )
        status = result.get("verification_status", "")
        return status == "SUCCESS", "verification_status=%s" % status
