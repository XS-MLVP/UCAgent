#coding=utf8


import threading
from collections import deque

class CircularOverwriteQueue:
    def __init__(self, maxsize):
        if maxsize <= 0:
            raise ValueError("maxsize need > 0")
        self.maxsize = maxsize
        self.queue = deque(maxlen=maxsize)
        self.lock = threading.Lock()

    def put(self, item):
        with self.lock:
            self.queue.append(item)

    def get(self):
        with self.lock:
            if len(self.queue) == 0:
                raise IndexError("Queue is empty")
            return self.queue.popleft()

    def try_get(self):
        with self.lock:
            if len(self.queue) == 0:
                return None
            return self.queue.popleft()

    def size(self):
        with self.lock:
            return len(self.queue)

    def is_empty(self):
        with self.lock:
            return len(self.queue) == 0

    def is_full(self):
        with self.lock:
            return len(self.queue) == self.maxsize

    def clear(self):
        with self.lock:
            self.queue.clear()

    def __str__(self):
        with self.lock:
            if self.is_empty():
                return ""
            return ''.join([str(item) for item in self.queue])
