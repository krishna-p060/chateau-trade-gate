"""Purchasing mandates: what a buyer organisation authorises its agent to do.

Encoded as a W3C Verifiable Credential (VC Data Model 2.0) secured as a JWT (vc-jwt, EdDSA).
The buyer signs it; Valio's gate verifies it and enforces it server-side, so limits hold even if
the agent's prompt is wrong or the agent is compromised.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

from trade_gate.trust.keys import KeyPair, verify

MANDATE_TYPE = "PurchasingMandate"


@dataclass
class Limits:
    auto_approve_max_order_eur: float = 1500.0   # orders up to this go through without a human
    hard_max_order_eur: float = 20000.0          # never, even with approval
    weekly_budget_eur: float = 15000.0           # approval needed once weekly spend would exceed
    max_unit_price_increase_pct: float = 15.0    # vs the buyer's reference price -> approval


@dataclass
class DietaryRules:
    avoid_allergens: list[str] = field(default_factory=list)  # hard block (CONTAINS or MAY_CONTAIN)
    require_allergen_data: bool = False                        # missing declarations -> approval
    required_diets: list[str] = field(default_factory=list)    # e.g. ['lactose_free'] for specific categories


@dataclass
class SubstitutionRules:
    allowed: bool = True
    approval_outside_preferences: bool = True
    max_price_increase_pct: float = 10.0


@dataclass
class DeliveryRules:
    unconfirmed_stock_needs_approval: bool = True   # supplier-warehouse items with unknown stock
    estimated_dates_need_approval: bool = True      # dates we estimated after a passed cut-off


@dataclass
class Mandate:
    buyer_id: str
    buyer_name: str
    agent_id: str
    limits: Limits = field(default_factory=Limits)
    dietary: DietaryRules = field(default_factory=DietaryRules)
    substitution: SubstitutionRules = field(default_factory=SubstitutionRules)
    delivery: DeliveryRules = field(default_factory=DeliveryRules)
    blocked_categories: list[str] = field(default_factory=list)
    approvers: list[str] = field(default_factory=lambda: ["Head chef"])
    valid_days: int = 30

    def to_credential_subject(self) -> dict:
        d = asdict(self)
        d.pop("valid_days")
        d["id"] = f"urn:agent:{self.agent_id}"
        return d

    @staticmethod
    def from_credential_subject(cs: dict) -> "Mandate":
        return Mandate(
            buyer_id=cs["buyer_id"], buyer_name=cs["buyer_name"], agent_id=cs["agent_id"],
            limits=Limits(**cs.get("limits", {})), dietary=DietaryRules(**cs.get("dietary", {})),
            substitution=SubstitutionRules(**cs.get("substitution", {})),
            delivery=DeliveryRules(**cs.get("delivery", {})),
            blocked_categories=cs.get("blocked_categories", []), approvers=cs.get("approvers", []))


def issue(mandate: Mandate, buyer_key: KeyPair) -> str:
    now = int(time.time())
    payload = {
        "iss": f"urn:buyer:{mandate.buyer_id}",
        "sub": f"urn:agent:{mandate.agent_id}",
        "iat": now, "nbf": now, "exp": now + mandate.valid_days * 86400,
        "vc": {
            "@context": ["https://www.w3.org/ns/credentials/v2"],
            "type": ["VerifiableCredential", MANDATE_TYPE],
            "issuer": f"urn:buyer:{mandate.buyer_id}",
            "credentialSubject": mandate.to_credential_subject(),
        },
    }
    return buyer_key.sign(payload, typ="vc+jwt")


def verify_mandate(token: str, buyer_jwk: dict) -> Mandate:
    claims = verify(token, buyer_jwk)
    vc = claims.get("vc") or {}
    if MANDATE_TYPE not in (vc.get("type") or []):
        raise ValueError("credential is not a PurchasingMandate")
    return Mandate.from_credential_subject(vc["credentialSubject"])
