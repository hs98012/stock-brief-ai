"""Opt-in serialization of local inference in the single-worker dev profile."""
import os
from functools import wraps
from threading import RLock

_lock = RLock()


def serial_local_inference(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if os.getenv("STOCK_BRIEF_LOW_MEMORY") == "1":
            with _lock:
                return function(*args, **kwargs)
        return function(*args, **kwargs)
    return wrapped
