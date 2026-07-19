import json
import os

FILE = "data.json"


def load():
    if not os.path.exists(FILE):
        return []

    with open(FILE, "r") as f:
        return json.load(f)


def save(history):
    with open(FILE, "w") as f:
        json.dump(history, f, indent=4)


def add(text):
    history = load()

    if text and (not history or history[0] != text):
        history.insert(0, text)

    history = history[:100]

    save(history)


def show():
    history = load()

    if not history:
        print("No clipboard history.")
        return

    for i, item in enumerate(history, 1):
        preview = item.replace("\n", " ")[:50]
        print(f"{i}. {preview}")