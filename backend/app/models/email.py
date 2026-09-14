"""The shape of an email once we have pulled it out of the Gmail payload.

This is the contract between Abhiram's Gmail layer, Satwik's classifier, and
Akansha's Firestore layer — everything downstream reads these fields.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class EmailMessage(BaseModel):
    id: str                      # Gmail message id, also the Firestore doc id
    thread_id: str
    sender: str                  # raw From header, e.g. 'Nike <news@nike.com>'
    sender_email: str            # just the address
    sender_domain: str
    to: str = ""
    subject: str = ""
    date: datetime | None = None
    snippet: str = ""
    body_text: str = ""          # plain-text body, HTML stripped
    labels: list[str] = Field(default_factory=list)

    # filled in later by the classifier (Satwik)
    category: str | None = None
    confidence: float | None = None

    # filled in for category == "subscription" by extract_subscription_info
    sub_service: str | None = None
    sub_amount: str | None = None
    sub_cycle: str | None = None          # monthly | yearly | trial
    sub_renewal_hint: str | None = None   # raw text near the renewal date, not parsed

    # filled in for category == "promotion" by extract_promo_subcategory
    promo_subcategory: str | None = None
