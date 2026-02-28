import asyncio
import json
from collections import deque
from collections.abc import AsyncGenerator
from contextlib import suppress
from time import perf_counter
from typing import Any

from firefly_categorizer.domain.timefmt import format_duration
from firefly_categorizer.domain.transactions import build_transaction_snapshot
from firefly_categorizer.integration.firefly import FireflyClient, FireflyConfigurationError
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
        self._stream_task: asyncio.Task[None] | None = None
        self._stream_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._stream_lock = asyncio.Lock()

    def reset_state(self) -> int:
        cleared = len(self.seen_ids)
        self.seen_ids.clear()
        task = self._stream_task
        if task and not task.done():
            self._publish_status(
                {
                    "stage": "error",
                    "message": "Training cancelled.",
                },
                active=False,
            )
            task.cancel()
        self._stream_task = None
        self._stream_subscribers.clear()
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

    def _publish_status(self, payload: dict[str, Any], *, active: bool) -> None:
        self.status.clear()
        self.status.update({**payload, "active": active})
        for queue in tuple(self._stream_subscribers):
            if queue.full():
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with suppress(asyncio.QueueFull):
                queue.put_nowait(payload)

    async def _ensure_stream_task(self) -> None:
        async with self._stream_lock:
            if self._stream_task and not self._stream_task.done():
                return
            self._stream_task = asyncio.create_task(self._run_training_stream())

    def _process_training_page(
        self,
        page_txs: list[dict[str, Any]],
    ) -> tuple[int, int, int]:
        trained_count = 0
        skipped_uncategorized = 0
        skipped_duplicate = 0

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

            self.service.learn(snapshot.transaction, Category(name=category_name))
            trained_count += 1
            if tx_id:
                self.seen_ids.add(tx_id)

        return trained_count, skipped_uncategorized, skipped_duplicate

    async def train_bulk(self) -> dict[str, Any]:
        logger.info("[TRAIN] Starting bulk training from Firefly data...")
        self.firefly.require_credentials()

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

    async def _run_training_stream(self) -> None:
        if not self.service or not self.firefly:
            self._publish_status(
                {
                    "stage": "error",
                    "message": "Service not initialized",
                },
                active=False,
            )
            return

        try:
            self.firefly.require_credentials()
        except FireflyConfigurationError as exc:
            self._publish_status(
                {
                    "stage": "error",
                    "message": str(exc),
                },
                active=False,
            )
            return

        trained_count = 0
        skipped_count = 0
        skipped_duplicate = 0
        total_fetched = 0
        total_estimate = 0
        last_fetch_durations: deque[float] = deque(maxlen=10)
        last_train_durations: deque[float] = deque(maxlen=10)
        last_total_durations: deque[float] = deque(maxlen=10)
        avg_fetch_last_10_seconds = 0.0
        avg_train_last_10_seconds = 0.0
        avg_total_last_10_seconds = 0.0
        pause_requested = False

        self.active = True
        self.pause_event.clear()
        self._publish_status(
            {
                "stage": "start",
                "trained": 0,
                "skipped": 0,
                "fetched": 0,
                "total": 0,
                "percent": 0,
                "avg_fetch_last_10_seconds": 0.0,
                "avg_train_last_10_seconds": 0.0,
                "avg_total_last_10_seconds": 0.0,
                "avg_last_10_seconds": 0.0,
                "avg_last_10_display": None,
            },
            active=True,
        )

        try:
            transaction_pages = self.firefly.yield_transactions(limit_per_page=self.page_size).__aiter__()
            while True:
                if self.pause_event.is_set():
                    pause_requested = True
                    break

                page_fetch_started = perf_counter()
                try:
                    page_txs, meta = await transaction_pages.__anext__()
                except StopAsyncIteration:
                    break
                page_fetch_seconds = perf_counter() - page_fetch_started

                if self.pause_event.is_set():
                    pause_requested = True
                    break

                if total_estimate == 0:
                    total_estimate = meta.get("total", 0)

                total_fetched += len(page_txs)

                page_process_started = perf_counter()
                (
                    page_trained,
                    page_skipped_uncategorized,
                    page_skipped_duplicate,
                ) = await asyncio.to_thread(self._process_training_page, page_txs)
                page_process_seconds = perf_counter() - page_process_started
                trained_count += page_trained
                skipped_count += page_skipped_uncategorized
                skipped_duplicate += page_skipped_duplicate

                page_count = len(page_txs)
                if page_count > 0:
                    fetch_per_tx_seconds = page_fetch_seconds / page_count
                    train_per_tx_seconds = page_process_seconds / page_count
                    total_per_tx_seconds = fetch_per_tx_seconds + train_per_tx_seconds
                    # Keep one representative sample per page to smooth across pages.
                    last_fetch_durations.append(fetch_per_tx_seconds)
                    last_train_durations.append(train_per_tx_seconds)
                    last_total_durations.append(total_per_tx_seconds)
                    avg_fetch_last_10_seconds = (
                        sum(last_fetch_durations) / len(last_fetch_durations)
                    )
                    avg_train_last_10_seconds = (
                        sum(last_train_durations) / len(last_train_durations)
                    )
                    avg_total_last_10_seconds = (
                        sum(last_total_durations) / len(last_total_durations)
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
                    "avg_fetch_last_10_seconds": avg_fetch_last_10_seconds,
                    "avg_train_last_10_seconds": avg_train_last_10_seconds,
                    "avg_total_last_10_seconds": avg_total_last_10_seconds,
                    # Backward compatibility for older clients expecting one value.
                    "avg_last_10_seconds": avg_total_last_10_seconds,
                    "avg_last_10_display": (
                        format_duration(avg_total_last_10_seconds)
                        if last_total_durations
                        else None
                    ),
                }
                self._publish_status(status_payload, active=True)

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
                    "avg_fetch_last_10_seconds": (
                        avg_fetch_last_10_seconds if last_total_durations else 0.0
                    ),
                    "avg_train_last_10_seconds": (
                        avg_train_last_10_seconds if last_total_durations else 0.0
                    ),
                    "avg_total_last_10_seconds": (
                        avg_total_last_10_seconds if last_total_durations else 0.0
                    ),
                    "avg_last_10_seconds": (
                        avg_total_last_10_seconds if last_total_durations else 0.0
                    ),
                    "avg_last_10_display": (
                        format_duration(avg_total_last_10_seconds)
                        if last_total_durations
                        else None
                    ),
                }
                self._publish_status(pause_payload, active=False)
                return

            complete_payload = {
                "stage": "complete",
                "trained": trained_count,
                "skipped": skipped_count,
                "total_fetched": total_fetched,
                "avg_fetch_last_10_seconds": (
                    avg_fetch_last_10_seconds if last_total_durations else 0.0
                ),
                "avg_train_last_10_seconds": (
                    avg_train_last_10_seconds if last_total_durations else 0.0
                ),
                "avg_total_last_10_seconds": (
                    avg_total_last_10_seconds if last_total_durations else 0.0
                ),
                "avg_last_10_seconds": (
                    avg_total_last_10_seconds if last_total_durations else 0.0
                ),
                "avg_last_10_display": (
                    format_duration(avg_total_last_10_seconds)
                    if last_total_durations
                    else None
                ),
            }
            self._publish_status(complete_payload, active=False)
        except asyncio.CancelledError:
            logger.info("[TRAIN] Training stream task cancelled.")
            if self._stream_subscribers:
                self._publish_status(
                    {
                        "stage": "error",
                        "message": "Training cancelled.",
                    },
                    active=False,
                )
            raise
        except FireflyConfigurationError as exc:
            logger.warning("[TRAIN] Training blocked by Firefly configuration: %s", exc)
            self._publish_status(
                {
                    "stage": "error",
                    "message": str(exc),
                },
                active=False,
            )
        except Exception:
            logger.exception("[TRAIN] Training failed with an unexpected error.")
            self._publish_status(
                {
                    "stage": "error",
                    "message": "Training failed. Check server logs.",
                },
                active=False,
            )
        finally:
            self.active = False
            self.pause_event.clear()
            self.status["active"] = False
            self._stream_task = None

    async def stream(self) -> AsyncGenerator[str, None]:
        if not self.service or not self.firefly:
            error_payload = {
                "stage": "error",
                "message": "Service not initialized",
            }
            self._publish_status(error_payload, active=False)
            yield f"data: {json.dumps(error_payload)}\n\n"
            return

        subscriber: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        self._stream_subscribers.add(subscriber)
        try:
            current_status = self.get_status()
            current_stage = current_status.get("stage")
            if current_stage in {"start", "processing"} or current_status.get("active"):
                snapshot_payload = dict(current_status)
                snapshot_payload.pop("active", None)
                yield f"data: {json.dumps(snapshot_payload)}\n\n"

            await self._ensure_stream_task()
            while True:
                payload = await subscriber.get()
                yield f"data: {json.dumps(payload)}\n\n"
                if payload.get("stage") in {"complete", "paused", "error"}:
                    break
        finally:
            self._stream_subscribers.discard(subscriber)
