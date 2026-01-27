import asyncio

from firefly_categorizer.core import settings
from firefly_categorizer.domain.tags import merge_tags
from firefly_categorizer.domain.transactions import TransactionSnapshot
from firefly_categorizer.integration.firefly import FireflyClient
from firefly_categorizer.logger import get_logger
from firefly_categorizer.manager import CategorizerService
from firefly_categorizer.models import CategorizationResult, Transaction

logger = get_logger(__name__)


class CategorizationPipeline:
    def __init__(
        self,
        service: CategorizerService,
        firefly: FireflyClient,
    ) -> None:
        self.service = service
        self.firefly = firefly

    async def predict(
        self,
        transaction: Transaction,
        *,
        valid_categories: list[str] | None = None,
    ) -> CategorizationResult | None:
        return await asyncio.to_thread(
            self.service.categorize,
            transaction,
            valid_categories=valid_categories,
        )

    async def maybe_auto_approve(
        self,
        transaction_id: str | int,
        transaction: Transaction,
        prediction: CategorizationResult,
        existing_tags: list[str],
        *,
        include_existing_when_no_auto: bool = False,
        log_auto_approve: bool = True,
        log_disabled: bool = False,
        log_low_confidence: bool = False,
        threshold: float | None = None,
    ) -> bool:
        success, _ = await self.evaluate_auto_approval(
            transaction_id,
            transaction,
            prediction,
            existing_tags,
            include_existing_when_no_auto=include_existing_when_no_auto,
            log_auto_approve=log_auto_approve,
            log_disabled=log_disabled,
            log_low_confidence=log_low_confidence,
            threshold=threshold,
        )
        return success

    def auto_approval_reason(
        self,
        transaction_id: str | int,
        prediction: CategorizationResult,
        *,
        threshold: float | None = None,
        log_disabled: bool = False,
        log_low_confidence: bool = False,
    ) -> tuple[str | None, float]:
        if threshold is None:
            threshold = settings.get_env_float("AUTO_APPROVE_THRESHOLD", 0.0)
        if threshold <= 0:
            if log_disabled:
                logger.info(
                    "[WEBHOOK] Auto-approve disabled (AUTO_APPROVE_THRESHOLD=%s). Suggested '%s'.",
                    threshold,
                    prediction.category.name,
                )
            return "disabled", threshold

        if prediction.confidence < threshold:
            if log_low_confidence:
                logger.info(
                    "[WEBHOOK] Confidence %.2f below threshold %.2f for transaction %s; suggested '%s'.",
                    prediction.confidence,
                    threshold,
                    transaction_id,
                    prediction.category.name,
                )
            return "low_confidence", threshold

        return None, threshold

    async def evaluate_auto_approval(
        self,
        transaction_id: str | int,
        transaction: Transaction,
        prediction: CategorizationResult,
        existing_tags: list[str],
        *,
        include_existing_when_no_auto: bool = False,
        log_auto_approve: bool = True,
        log_disabled: bool = False,
        log_low_confidence: bool = False,
        threshold: float | None = None,
    ) -> tuple[bool, str]:
        reason, threshold_value = self.auto_approval_reason(
            transaction_id,
            prediction,
            threshold=threshold,
            log_disabled=log_disabled,
            log_low_confidence=log_low_confidence,
        )
        if reason:
            return False, reason

        success = await self.apply_auto_approval(
            transaction_id,
            transaction,
            prediction,
            existing_tags,
            include_existing_when_no_auto=include_existing_when_no_auto,
            log_auto_approve=log_auto_approve,
            threshold=threshold_value,
        )
        return success, "updated" if success else "failed"

    async def predict_for_snapshot(
        self,
        snapshot: TransactionSnapshot,
        *,
        valid_categories: list[str] | None = None,
        auto_approve_threshold: float = 0.0,
    ) -> tuple[CategorizationResult | None, str | None, bool]:
        existing_cat = snapshot.category_name
        prediction: CategorizationResult | None = None
        auto_approved = False

        if not existing_cat:
            tx_id_log = snapshot.transaction_id if snapshot.transaction_id is not None else "unknown"
            logger.debug(
                "[PREDICT] Starting categorization for transaction ID: %s",
                tx_id_log,
            )
            prediction = await self.predict(
                snapshot.transaction,
                valid_categories=valid_categories,
            )

            if prediction and snapshot.transaction_id is not None:
                success = await self.maybe_auto_approve(
                    snapshot.transaction_id,
                    snapshot.transaction,
                    prediction,
                    snapshot.tags,
                    threshold=auto_approve_threshold,
                )
                if success:
                    existing_cat = prediction.category.name
                    auto_approved = True
                    prediction = None

        return prediction, existing_cat, auto_approved

    async def apply_auto_approval(
        self,
        transaction_id: str | int,
        transaction: Transaction,
        prediction: CategorizationResult,
        existing_tags: list[str],
        *,
        include_existing_when_no_auto: bool = False,
        log_auto_approve: bool = True,
        threshold: float | None = None,
    ) -> bool:
        transaction_id_value = str(transaction_id)

        if log_auto_approve:
            threshold_value = threshold if threshold is not None else prediction.confidence
            logger.info(
                "[AUTO-APPROVE] Transaction %s: '%s' (confidence: %.2f >= %.2f)",
                transaction_id_value,
                prediction.category.name,
                prediction.confidence,
                threshold_value,
            )

        auto_tags = settings.get_env_tags("AUTO_APPROVE_TAGS")
        if auto_tags:
            tags_payload = merge_tags(existing_tags, auto_tags)
        else:
            tags_payload = existing_tags if include_existing_when_no_auto else None

        success = await self.firefly.update_transaction(
            transaction_id_value,
            prediction.category.name,
            tags=tags_payload,
        )
        if success:
            await asyncio.to_thread(self.service.learn, transaction, prediction.category)
        return success
