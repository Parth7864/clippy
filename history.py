import json
import os
from datetime import datetime

FILE = "data.json"
MAX_ITEMS = 200


def load():
    if not os.path.exists(FILE):
        return []
    with open(FILE) as f:
        data = json.load(f)
    if data and isinstance(data[0], str):
        data = [{"text": item, "time": ""} for item in data]
        save(data)
    return data


def save(items):
    with open(FILE, "w") as f:
        json.dump(items, f, indent=2)


def add(text):
    if not text:
        return []
    items = load()
    if items and items[0].get("text") == text:
        return items
    items.insert(0, {"text": text, "time": datetime.now().isoformat(timespec="seconds")})
    items = items[:MAX_ITEMS]
    save(items)
    return items


def remove(index):
    items = load()
    if 0 <= index < len(items):
        del items[index]
        save(items)
    return items


def clear():
    save([])


def search(query):
    items = load()
    q = query.lower()
    return [(i, item) for i, item in enumerate(items) if q in item["text"].lower()]


def get(index):
    items = load()
    if 0 <= index < len(items):
        return items[index]
    return None


def count():
    return len(load())
