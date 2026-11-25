"""Retain shared trace clients until every overlapping Agent instance has retired."""

import threading


_CLIENTS = {}
_LOCK = threading.RLock()


def acquire_trace_client(factory, **options):
    """Share one credential-scoped client and return an independently idempotent release."""
    key = (factory, tuple(sorted(options.items())))
    with _LOCK:
        if key not in _CLIENTS:
            client = factory(**options)
            try:
                if not client.auth_check():
                    raise RuntimeError("Cannot connect to configured trace service")
            except BaseException:
                client.shutdown()
                raise
            _CLIENTS[key] = [client, 0]
        entry = _CLIENTS[key]
        entry[1] += 1
    released = False

    def release():
        """Drain the client only after the last instance's workers and callbacks stop."""
        nonlocal released
        with _LOCK:
            if released:
                return
            if entry[1] == 1:
                entry[0].shutdown()
                del _CLIENTS[key]
            else:
                entry[1] -= 1
            released = True
    return entry[0], release
