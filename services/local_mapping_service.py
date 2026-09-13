"""Fast, offline, client-scoped transaction categorization.

No transaction text leaves the machine. The matching order is deliberately
deterministic: learned vendor -> configured rule -> confirmed history -> local
similarity. Low-confidence suggestions remain in suspense for review.
"""
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from core.models import CategoryRule, LearnedMapping, Transaction

SUSPENSE_CATEGORIES = {"", "uncategorized", "suspense expense", "suspense revenue"}


@dataclass(frozen=True)
class MappingResult:
    category: str
    confidence: float
    source: str
    explanation: str
    review_required: bool


def normalize_vendor(value: str) -> str:
    text = re.sub(r"[^A-Z0-9 ]+", " ", (value or "").upper())
    text = re.sub(r"\b(?:POS|DEBIT|CREDIT|PURCHASE|PAYMENT|ONLINE|CARD|VISA|MC)\b", " ", text)
    text = re.sub(r"\b\d{3,}\b", " ", text)
    return " ".join(text.split())[:255]


def is_suspense(category: Optional[str]) -> bool:
    return (category or "").strip().lower() in SUSPENSE_CATEGORIES


def _rule_matches(rule: CategoryRule, description: str) -> bool:
    keyword = (rule.keyword or "").strip()
    if keyword.lower().startswith("regex:"):
        try:
            return re.search(keyword[6:].strip(), description, re.IGNORECASE) is not None
        except re.error:
            return False
    return keyword.upper() in description.upper()


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    left_tokens, right_tokens = set(left.split()), set(right.split())
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
    sequence = SequenceMatcher(None, left, right).ratio()
    return 0.65 * jaccard + 0.35 * sequence


def learn_mapping(db: Session, client_id: int, description: str, category: str,
                  gst_treatment: str = "Standard", itc_eligible: bool = True,
                  business_pct: float = 100.0, commit: bool = True) -> Optional[LearnedMapping]:
    vendor = normalize_vendor(description)
    if not vendor or is_suspense(category):
        return None
    # SessionLocal uses autoflush=False. During a statement import, an earlier
    # mapping for this vendor may therefore still be in db.new and invisible to
    # a SELECT. Reuse it so repeated vendors produce one INSERT per client.
    mapping = next((item for item in db.new if (
        isinstance(item, LearnedMapping)
        and item.client_id == client_id
        and item.normalized_vendor == vendor
    )), None)
    if mapping is None:
        mapping = db.query(LearnedMapping).filter(
            LearnedMapping.client_id == client_id,
            LearnedMapping.normalized_vendor == vendor,
        ).first()
    if mapping:
        mapping.category = category
        mapping.sample_description = description
        mapping.gst_treatment = gst_treatment
        mapping.itc_eligible = itc_eligible
        mapping.business_pct = business_pct
        mapping.confirmation_count = (mapping.confirmation_count or 0) + 1
    else:
        mapping = LearnedMapping(
            client_id=client_id, normalized_vendor=vendor,
            sample_description=description, category=category,
            gst_treatment=gst_treatment, itc_eligible=itc_eligible,
            business_pct=business_pct, confirmation_count=1,
        )
        db.add(mapping)
    if commit:
        db.commit()
        db.refresh(mapping)
    return mapping


class LocalMappingEngine:
    def __init__(self, db: Session, client_id: int, auto_apply_threshold: float = 0.86):
        self.db = db
        self.client_id = client_id
        self.auto_apply_threshold = auto_apply_threshold
        self.learned = db.query(LearnedMapping).filter(LearnedMapping.client_id == client_id).all()
        self.rules = db.query(CategoryRule).filter(CategoryRule.client_id == client_id).all()
        self.history = self._build_history()

    def _build_history(self):
        rows = self.db.query(Transaction).filter(Transaction.client_id == self.client_id).all()
        grouped = defaultdict(lambda: defaultdict(int))
        samples = {}
        for tx in rows:
            if is_suspense(tx.category) or tx.review_required:
                continue
            vendor = normalize_vendor(tx.cleaned_description or tx.original_description)
            if vendor:
                grouped[vendor][tx.category] += 1
                samples[vendor] = tx.cleaned_description or tx.original_description
        history = []
        for vendor, counts in grouped.items():
            category, count = max(counts.items(), key=lambda pair: pair[1])
            total = sum(counts.values())
            history.append((vendor, category, count / total, total, samples[vendor]))
        return history

    def categorize(self, description: str, original_description: str = "", amount: float = 0.0) -> MappingResult:
        combined = " ".join(part for part in (description, original_description) if part)
        vendor = normalize_vendor(description or original_description)
        suspense = "Suspense Revenue" if amount > 0 else "Suspense Expense"

        exact = next((m for m in self.learned if m.normalized_vendor == vendor), None)
        if exact:
            return MappingResult(exact.category, 0.99, "learned_vendor", "Confirmed client vendor mapping", False)

        matches = [r for r in self.rules if _rule_matches(r, combined)]
        if matches:
            rule = max(matches, key=lambda r: len(r.keyword or ""))
            return MappingResult(rule.category, 1.0, "regex_rule" if rule.keyword.lower().startswith("regex:") else "keyword_rule", "Matched a client rule", False)

        exact_history = next((h for h in self.history if h[0] == vendor), None)
        if exact_history:
            confidence = min(0.98, 0.88 + min(exact_history[3], 10) * 0.01) * exact_history[2]
            return self._result(exact_history[1], confidence, "client_history", "Consistent prior client classification")

        candidates = [(m.normalized_vendor, m.category, _similarity(vendor, m.normalized_vendor)) for m in self.learned]
        candidates += [(h[0], h[1], _similarity(vendor, h[0])) for h in self.history]
        if candidates:
            _, category, score = max(candidates, key=lambda item: item[2])
            confidence = min(0.90, score * 0.96)
            if score >= 0.62:
                return self._result(category, confidence, "local_similarity", "Similar to a confirmed client transaction")
        return MappingResult(suspense, 0.0, "unmatched", "No reliable local match", True)

    def _result(self, category: str, confidence: float, source: str, explanation: str) -> MappingResult:
        confidence = round(max(0.0, min(1.0, confidence)), 3)
        review = confidence < self.auto_apply_threshold
        return MappingResult(category if not review else category, confidence, source, explanation, review)

    def categorize_many(self, transactions: Iterable[dict]):
        return [self.categorize(
            tx.get("cleaned_description", ""), tx.get("original_description", ""), tx.get("amount", 0.0)
        ) for tx in transactions]


def apply_to_suspense_transactions(db: Session, client_id: int, threshold: float = 0.86):
    engine = LocalMappingEngine(db, client_id, threshold)
    transactions = db.query(Transaction).filter(Transaction.client_id == client_id).all()
    updated = review = 0
    for tx in transactions:
        if not is_suspense(tx.category):
            continue
        result = engine.categorize(tx.cleaned_description, tx.original_description, tx.amount)
        tx.confidence = result.confidence
        tx.review_required = result.review_required
        if not result.review_required:
            tx.category = result.category
            updated += 1
        else:
            review += 1
    db.commit()
    return {"updated": updated, "review": review}
