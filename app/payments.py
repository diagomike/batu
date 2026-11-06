"""Payment providers.

The portal only needs three things from a provider:
  1. start(payment_id, amount, description, return_url) -> URL to send the payer to
  2. a callback or return that tells us the payment succeeded
  3. a receipt number

DemoProvider simulates a Telebirr-style checkout inside the portal; no money moves.
To go live, implement TelebirrProvider.start/verify with your integration and set
PAYMENT_PROVIDER=telebirr in .env.
"""
from __future__ import annotations

import os


class DemoProvider:
    name = "demo"
    label = "Telebirr (demo, no money moves)"

    def start(self, payment_id: str, amount: float, description: str, return_url: str) -> str:
        return f"/pay/demo-checkout/{payment_id}"

    def verify(self, payment_id: str, params: dict) -> bool:
        return params.get("result") == "success"


class TelebirrProvider(DemoProvider):
    """Plug your Telebirr (or bank gateway) integration in here."""
    name = "telebirr"
    label = "Telebirr"

    def start(self, payment_id, amount, description, return_url):  # pragma: no cover - needs credentials
        raise NotImplementedError("Add your Telebirr checkout call here and return its redirect URL.")

    def verify(self, payment_id, params):  # pragma: no cover
        raise NotImplementedError("Verify the provider's signed callback here.")


def provider():
    return TelebirrProvider() if os.getenv("PAYMENT_PROVIDER", "demo") == "telebirr" else DemoProvider()
