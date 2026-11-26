"""Content-addressed, request-local reuse of strict read-only verification."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
import hashlib
import json

_cache = ContextVar('verification_cache', default=None)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), default=str).encode()).hexdigest()


@contextmanager
def verification_request():
    if _cache.get() is not None:
        yield
        return
    token = _cache.set({})
    try:
        yield
    finally:
        _cache.reset(token)


def request_verified(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with verification_request():
            return function(*args, **kwargs)
    return wrapped


def memoized(kind, key, verify, *, copy=True):
    cache = _cache.get()
    if cache is None:
        return verify()
    cache_key = (kind, key)
    if cache_key not in cache:
        cache[cache_key] = verify()
    return deepcopy(cache[cache_key]) if copy else cache[cache_key]


def object_fingerprint(owner, identical, equal, compute):
    """Reuse a fingerprint inside one request only for the very same live objects.

    `identical` parts must be the same objects and `equal` parts must compare equal;
    the entry keeps references so an id cannot be reused by another object.
    """
    cache = _cache.get()
    if cache is None:
        return compute()
    entry = cache.get(('object_fingerprint', id(owner)))
    if (entry is None or entry[1] != equal or len(entry[0]) != len(identical)
            or any(a is not b for a, b in zip(entry[0], identical))):
        entry = cache[('object_fingerprint', id(owner))] = (identical, equal, compute())
    return entry[2]


def active():
    return _cache.get() is not None
