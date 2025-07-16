# app/temp_store.py
from collections import defaultdict
import time

class TempStore:
    def __init__(self):
        self.data = {}

    def set(self, key, value, ttl=300):
        self.data[key] = (value, time.time() + ttl)

    def get(self, key):
        value = self.data.get(key)
        if not value:
            return None
        val, expires = value
        if time.time() > expires:
            del self.data[key]
            return None
        return val

temp_store = TempStore()
