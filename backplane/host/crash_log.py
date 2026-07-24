"""Crash/exception logging for the Backplane host process.

Every host_api.py handler and background thread should end up routed
through the logger this module configures, so a bug never fails silently.
"""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_crash_logging(log_path: Path, logger_name: str = "backplane") -> logging.Logger:
    """Configure a logger and hook uncaught exceptions on the main thread
    and background threads into it. Idempotent: safe to call more than once
    with the same logger_name (handlers aren't duplicated).

    Callers that create a Tk root should also set the root's
    ``report_callback_exception`` to ``tk_report_callback_exception(logger)``,
    since Tk swallows exceptions raised inside callbacks otherwise.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(handler)

    def _excepthook(exc_type, exc_value, exc_tb):
        logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))

    def _threading_excepthook(args: "threading.ExceptHookArgs") -> None:
        thread_name = args.thread.name if args.thread is not None else "?"
        logger.critical(
            "Unhandled exception in thread %s",
            thread_name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _excepthook
    threading.excepthook = _threading_excepthook

    return logger


def tk_report_callback_exception(logger: logging.Logger):
    """Build a callable suitable for assignment to a Tk root's
    ``report_callback_exception`` attribute."""

    def _handler(exc_type, exc_value, exc_tb):
        logger.critical(
            "Unhandled exception in Tk callback",
            exc_info=(exc_type, exc_value, exc_tb),
        )

    return _handler
