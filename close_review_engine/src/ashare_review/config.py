from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True, slots=True)
class StockConfig:
    code: str
    name: str
    exchange: str
    industry: str
    themes: tuple[str, ...]
    industry_logic: float

    @property
    def symbol(self) -> str:
        return ("sh" if self.exchange.upper() == "SH" else "sz") + self.code

    @property
    def secid(self) -> str:
        return ("1." if self.exchange.upper() == "SH" else "0.") + self.code


def load_universe(path: str | Path) -> list[StockConfig]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    raw = payload.get("stocks")
    if not isinstance(raw, list) or not raw:
        raise ValueError("universe config must contain a non-empty stocks list")
    result: list[StockConfig] = []
    seen: set[str] = set()
    for item in raw:
        code = str(item["code"]).zfill(6)
        if code in seen:
            raise ValueError(f"duplicate stock code: {code}")
        seen.add(code)
        result.append(
            StockConfig(
                code=code,
                name=str(item["name"]),
                exchange=str(item["exchange"]).upper(),
                industry=str(item["industry"]),
                themes=tuple(str(value) for value in item.get("themes", [])),
                industry_logic=float(item.get("industry_logic", 50)),
            )
        )
    return result
