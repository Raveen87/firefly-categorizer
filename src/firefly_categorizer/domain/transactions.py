from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from firefly_categorizer.domain.tags import normalize_tags
from firefly_categorizer.models import CategorizationResult, Transaction


@dataclass(frozen=True)
class TransactionSnapshot:
    transaction: Transaction
    transaction_id: str | int | None
    description: str
    amount: float
    currency: str
    date: datetime
    category_name: str | None
    tags: list[str]


def parse_date(value: str | datetime | None) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now()
    return datetime.now()


def _extract_transaction_attrs(t_data: dict[str, Any]) -> dict[str, Any]:
    attrs = t_data.get("attributes", {})
    nested = attrs.get("transactions", [{}])
    if isinstance(nested, list) and nested:
        candidate = nested[0]
        if isinstance(candidate, dict):
            return candidate
    return {}


def build_transaction_snapshot(t_data: dict[str, Any]) -> TransactionSnapshot:
    attrs = t_data.get("attributes", {})
    tx_attrs = _extract_transaction_attrs(t_data)
    description = tx_attrs.get("description", "")
    amount = float(tx_attrs.get("amount", 0.0))
    currency = tx_attrs.get("currency_code", "EUR")
    date_value = parse_date(tx_attrs.get("date", ""))
    category_name = tx_attrs.get("category_name")
    tags = normalize_tags(tx_attrs.get("tags") or attrs.get("tags"))
    tx_id = t_data.get("id")

    transaction = Transaction(
        description=description,
        amount=amount,
        date=date_value,
        currency=currency,
    )

    return TransactionSnapshot(
        transaction=transaction,
        transaction_id=tx_id,
        description=description,
        amount=amount,
        currency=currency,
        date=date_value,
        category_name=category_name,
        tags=tags,
    )


def build_transactions_display(raw_txs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    transactions_display = []
    for t_data in raw_txs:
        snapshot = build_transaction_snapshot(t_data)
        transactions_display.append(build_transaction_payload(
            snapshot,
            prediction=None,
            existing_category=snapshot.category_name,
            auto_approved=False,
        ))
    return transactions_display


def build_transaction_payload(
    snapshot: TransactionSnapshot,
    *,
    prediction: CategorizationResult | None,
    existing_category: str | None,
    auto_approved: bool,
) -> dict[str, Any]:
    return {
        "id": snapshot.transaction_id,
        "date_formatted": snapshot.date.strftime("%Y-%m-%d"),
        "description": snapshot.description,
        "amount": snapshot.amount,
        "currency": snapshot.currency,
        "prediction": prediction,
        "existing_category": existing_category,
        "existing_tags": snapshot.tags,
        "auto_approved": auto_approved,
        "raw_obj": snapshot.transaction.model_dump_json(),
    }


_WEBHOOK_ID_KEYS = ("transaction_id", "resource_id", "object_id", "entity_id", "id")


def _iter_webhook_containers(payload: Any) -> list[dict[str, Any]]:
    containers: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        containers.append(payload)
        for key in ("data", "content", "transaction", "attributes"):
            value = payload.get(key)
            if isinstance(value, dict):
                containers.append(value)

    for container in list(containers):
        attrs = container.get("attributes")
        if isinstance(attrs, dict):
            containers.append(attrs)
        for key in ("data", "content"):
            nested = container.get(key)
            if isinstance(nested, dict):
                containers.append(nested)
        txs = container.get("transactions")
        if isinstance(txs, list) and txs:
            first_tx = txs[0]
            if isinstance(first_tx, dict):
                containers.append(first_tx)

    return containers


def extract_webhook_transaction_id(payload: dict[str, Any]) -> str | None:
    for container in _iter_webhook_containers(payload):
        for key in _WEBHOOK_ID_KEYS:
            value = container.get(key)
            if value is not None and str(value).strip():
                return str(value)
    return None


def extract_webhook_transaction_snapshot(payload: dict[str, Any]) -> dict[str, Any] | None:
    for container in _iter_webhook_containers(payload):
        if "attributes" in container or "transactions" in container:
            return container
        if any(key in container for key in ("description", "amount", "date", "currency_code")):
            return container
    return None


def parse_webhook_transaction(
    snapshot: dict[str, Any]
) -> tuple[Transaction | None, str | None, list[str]]:
    attrs_value = snapshot.get("attributes")
    if isinstance(attrs_value, dict):
        attrs: dict[str, Any] = attrs_value
    else:
        attrs = snapshot

    tx_details: Any = attrs
    transactions = attrs.get("transactions")
    if isinstance(transactions, list) and transactions:
        tx_details = transactions[0]
    if not isinstance(tx_details, dict):
        return None, None, []

    description = str(tx_details.get("description") or "")
    try:
        amount = float(tx_details.get("amount", 0.0))
    except (TypeError, ValueError):
        amount = 0.0
    currency = tx_details.get("currency_code") or tx_details.get("currency") or "EUR"
    date_raw = tx_details.get("date") or tx_details.get("created_at") or tx_details.get("updated_at")

    date_value = parse_date(date_raw)

    category_name = tx_details.get("category_name") or attrs.get("category_name")
    tags = normalize_tags(tx_details.get("tags") or attrs.get("tags"))

    if not description:
        return None, category_name, tags

    return Transaction(
        description=description,
        amount=amount,
        date=date_value,
        currency=currency,
    ), category_name, tags
