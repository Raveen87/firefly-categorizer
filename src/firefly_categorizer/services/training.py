import asyncio
import json
from collections import deque
from collections.abc import AsyncGenerator
from time import perf_counter
from typing import Any

from firefly_categorizer.domain.timefmt import format_duration
from firefly_categorizer.domain.transactions import build_transaction_snapshot
from firefly_categorizer.integration.firefly import FireflyClient
from firefly_categorizer.logger import get_logger
from firefly_categorizer.manager import CategorizerService
from firefly_categorizer.models import Category

logger = get_logger(__name__)


class TrainingManager:
    def __init__(
        self,
        service: CategorizerService,
        firefly: FireflyClient,
        page_size: int,
    ) -> None:
        self.service = service
        self.firefly = firefly
        self.page_size = page_size
        self.pause_event = asyncio.Event()
        self.active = False
        self.seen_ids: set[str] = set()
        self.status: dict[str, Any] = {"stage": "idle", "active": False}

    def reset_state(self) -> int:
        cleared = len(self.seen_ids)
        self.seen_ids.clear()
        self.pause_event.clear()
        self.status.clear()
        self.status.update({"stage": "idle", "active": False})
        self.active = False
        return cleared

    def clear_seen_ids(self) -> int:
        cleared = len(self.seen_ids)
        self.seen_ids.clear()
        return cleared

    def request_pause(self) -> bool:
        if self.active:
            self.pause_event.set()
            return True
        return False

    def get_status(self) -> dict[str, Any]:
        status = dict(self.status)
        status["active"] = self.active
        return status

    def _process_training_page(
        self,
        page_txs: list[dict[str, Any]],
    ) -> tuple[int, int, int, list[float]]:
        trained_count = 0
        skipped_uncategorized = 0
        skipped_duplicate = 0
        durations: list[float] = []

        for t_data in page_txs:
            snapshot = build_transaction_snapshot(t_data)
            tx_id = str(snapshot.transaction_id) if snapshot.transaction_id is not None else None
            if tx_id and tx_id in self.seen_ids:
                skipped_duplicate += 1
                continue

            category_name = snapshot.category_name
            if not category_name:
                skipped_uncategorized += 1
                continue

            start = perf_counter()
            self.service.learn(snapshot.transaction, Category(name=category_name))
            durations.append(perf_counter() - start)
            trained_count += 1
            if tx_id:
                self.seen_ids.add(tx_id)

        return trained_count, skipped_uncategorized, skipped_duplicate, durations

    async def train_bulk(self) -> dict[str, Any]:
        logger.info("[TRAIN] Starting bulk training from Firefly data...")

        trained_count = 0
        skipped_count = 0
        skipped_duplicate = 0
        total_fetched = 0

        async for page_txs, _ in self.firefly.yield_transactions(limit_per_page=self.page_size):
            total_fetched += len(page_txs)

            (
                page_trained,
                page_skipped_uncategorized,
                page_skipped_duplicate,
                _,
            ) = await asyncio.to_thread(self._process_training_page, page_txs)
            trained_count += page_trained
            skipped_count += page_skipped_uncategorized
            skipped_duplicate += page_skipped_duplicate

            logger.info(
                "[TRAIN] Page processed. Skipped (already trained): %s, "
                "Skipped (uncategorized): %s, Total trained so far: %s",
                page_skipped_duplicate,
                page_skipped_uncategorized,
                trained_count,
            )

        logger.info(
            "[TRAIN] Complete! Trained: %s, "
            "Skipped (no category): %s, "
            "Skipped (already trained): %s",
            trained_count,
            skipped_count,
            skipped_duplicate,
        )

        return {
            "status": "success",
            "trained": trained_count,
            "skipped": skipped_count,
            "total": total_fetched,
            "fetched": total_fetched,
        }

    async def stream(self) -> AsyncGenerator[str, None]:
        if not self.service or not self.firefly:
            self.status.clear()
            self.status.update({
                "stage": "error",
                "message": "Service not initialized",
                "active": False,
            })
            yield f"data: {json.dumps({'stage': 'error', 'message': 'Service not initialized'})}\n\n"
            return

        trained_count = 0
        skipped_count = 0
        skipped_duplicate = 0
        total_fetched = 0
        total_estimate = 0
        last_durations: deque[float] = deque(maxlen=10)
        avg_last_10_seconds = 0.0
        pause_requested = False

        self.active = True
        self.pause_event.clear()
        self.status.clear()
        self.status.update({
            "stage": "start",
            "active": True,
            "trained": 0,
            "skipped": 0,
            "fetched": 0,
            "total": 0,
            "percent": 0,
            "avg_last_10_seconds": 0.0,
            "avg_last_10_display": None,
        })
        yield "data: {\"stage\": \"start\"}\n\n"

        try:
            async for page_txs, meta in self.firefly.yield_transactions(limit_per_page=self.page_size):
                if self.pause_event.is_set():
                    pause_requested = True
                    break

                if total_estimate == 0:
                    total_estimate = meta.get("total", 0)

                total_fetched += len(page_txs)

                (
                    page_trained,
                    page_skipped_uncategorized,
                    page_skipped_duplicate,
                    page_durations,
                ) = await asyncio.to_thread(self._process_training_page, page_txs)
                trained_count += page_trained
                skipped_count += page_skipped_uncategorized
                skipped_duplicate += page_skipped_duplicate
                last_durations.extend(page_durations)
                avg_last_10_seconds = (
                    sum(last_durations) / len(last_durations)
                    if last_durations
                    else 0.0
                )

                logger.info(
                    "[TRAIN] Page processed. Skipped (already trained): %s, "
                    "Skipped (uncategorized): %s, Total trained so far: %s",
                    page_skipped_duplicate,
                    page_skipped_uncategorized,
                    trained_count,
                )

                if self.pause_event.is_set():
                    pause_requested = True
                    break

                percent = round(total_fetched / total_estimate * 100, 1) if total_estimate > 0 else 0
                status_payload = {
                    "stage": "processing",
                    "trained": trained_count,
                    "skipped": skipped_count,
                    "fetched": total_fetched,
                    "total": total_estimate,
                    "percent": percent,
                    "avg_last_10_seconds": avg_last_10_seconds,
                    "avg_last_10_display": format_duration(avg_last_10_seconds) if last_durations else None,
                }
                self.status.clear()
                self.status.update({**status_payload, "active": True})
                yield f"data: {json.dumps(status_payload)}\n\n"

            if pause_requested:
                percent = round(total_fetched / total_estimate * 100, 1) if total_estimate > 0 else 0
                logger.info(
                    "[TRAIN] Training paused. Trained: %s, Skipped (no category): %s, "
                    "Skipped (already trained): %s",
                    trained_count,
                    skipped_count,
                    skipped_duplicate,
                )
                pause_payload = {
                    "stage": "paused",
                    "trained": trained_count,
                    "skipped": skipped_count,
                    "total_fetched": total_fetched,
                    "fetched": total_fetched,
                    "total": total_estimate,
                    "percent": percent,
                    "avg_last_10_seconds": avg_last_10_seconds if last_durations else 0.0,
                    "avg_last_10_display": format_duration(avg_last_10_seconds) if last_durations else None,
                }
                self.status.clear()
                self.status.update({**pause_payload, "active": False})
                yield f"data: {json.dumps(pause_payload)}\n\n"
                return

            complete_payload = {
                "stage": "complete",
                "trained": trained_count,
                "skipped": skipped_count,
                "total_fetched": total_fetched,
                "avg_last_10_seconds": avg_last_10_seconds if last_durations else 0.0,
                "avg_last_10_display": format_duration(avg_last_10_seconds) if last_durations else None,
            }
            self.status.clear()
            self.status.update({**complete_payload, "active": False})
            yield f"data: {json.dumps(complete_payload)}\n\n"
        finally:
            self.active = False
            self.pause_event.clear()
            self.status["active"] = False
