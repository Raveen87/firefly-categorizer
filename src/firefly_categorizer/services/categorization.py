import asyncio

from firefly_categorizer.core import settings
from firefly_categorizer.domain.tags import merge_tags
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
        if threshold is None:
            threshold = settings.get_env_float("AUTO_APPROVE_THRESHOLD", 0.0)
        if threshold <= 0:
            if log_disabled:
                logger.info(
                    "[WEBHOOK] Auto-approve disabled (AUTO_APPROVE_THRESHOLD=%s). Suggested '%s'.",
                    threshold,
                    prediction.category.name,
                )
            return False

        if prediction.confidence < threshold:
            if log_low_confidence:
                logger.info(
                    "[WEBHOOK] Confidence %.2f below threshold %.2f for transaction %s; suggested '%s'.",
                    prediction.confidence,
                    threshold,
                    transaction_id,
                    prediction.category.name,
                )
            return False

        return await self.apply_auto_approval(
            transaction_id,
            transaction,
            prediction,
            existing_tags,
            include_existing_when_no_auto=include_existing_when_no_auto,
            log_auto_approve=log_auto_approve,
            threshold=threshold,
        )

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
