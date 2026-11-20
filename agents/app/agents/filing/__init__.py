from . import ai_queue
from .router import router

__all__ = ["router", "on_startup", "on_shutdown"]


def on_startup() -> None:
    ai_queue.start()  # background worker that batches AI double-checks


def on_shutdown() -> None:
    ai_queue.stop()
