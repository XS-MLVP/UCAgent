# -*- coding: utf-8 -*-
"""Circular overwrite queue implementation."""

import threading
from collections import deque
from typing import Any, Optional


class CircularOverwriteQueue:
    """Thread-safe circular queue that overwrites old items when full."""

    def __init__(self, maxsize: int) -> None:
        """Initialize the circular queue.

        Args:
            maxsize: Maximum size of the queue.

        Raises:
            ValueError: If maxsize is not greater than 0.
        """
        if maxsize <= 0:
            raise ValueError("maxsize need > 0")
        self.maxsize = maxsize
        self.queue = deque(maxlen=maxsize)
        self.lock = threading.Lock()

    def put(self, item: Any) -> None:
        """Put an item into the queue.

        Args:
            item: Item to add to the queue.
        """
        with self.lock:
            self.queue.append(item)

    def get(self) -> Any:
        """Get an item from the queue.

        Returns:
            Item from the front of the queue.

        Raises:
            IndexError: If the queue is empty.
        """
        with self.lock:
            if len(self.queue) == 0:
                raise IndexError("Queue is empty")
            return self.queue.popleft()

    def try_get(self) -> Optional[Any]:
        """Try to get an item from the queue without raising an exception.

        Returns:
            Item from the front of the queue, or None if empty.
        """
        with self.lock:
            if len(self.queue) == 0:
                return None
            return self.queue.popleft()

    def size(self) -> int:
        """Get the current size of the queue.

        Returns:
            Current number of items in the queue.
        """
        with self.lock:
            return len(self.queue)

    def is_empty(self) -> bool:
        """Check if the queue is empty.

        Returns:
            True if the queue is empty, False otherwise.
        """
        with self.lock:
            return len(self.queue) == 0

    def is_full(self) -> bool:
        """Check if the queue is full.

        Returns:
            True if the queue is full, False otherwise.
        """
        with self.lock:
            return len(self.queue) == self.maxsize

    def clear(self) -> None:
        """Clear all items from the queue."""
        with self.lock:
            self.queue.clear()

    def __str__(self) -> str:
        """Return string representation of the queue contents."""
        with self.lock:
            if self.is_empty():
                return ""
            return ''.join([str(item) for item in self.queue])
