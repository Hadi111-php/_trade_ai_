"""ثبت کامل رویدادها در JSONL (فورنزیک) — هر سیگنال، هر وتو، هر معامله."""
from __future__ import annotations

import json
import os
from typing import Optional


class JsonlWriter:
    """نویسندهٔ JSONL با ساخت خودکار پوشه و بستن امن."""

    def __init__(self, path: str):
        self.path = path
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.f = open(path, "a", encoding="utf-8")
        self.count = 0

    def write(self, obj: dict) -> None:
        self.f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
        self.count += 1

    def close(self) -> None:
        try:
            self.f.close()
        except Exception:
            pass


def read_jsonl(path: str) -> list:
    if not path or not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out
