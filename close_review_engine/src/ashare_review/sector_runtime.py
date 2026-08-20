from __future__ import annotations

from datetime import date
from typing import Any

from ashare_review import sector_review as _base
from ashare_review.sector_data import fetch_board_constituents

_BaseLiveBoardProvider = _base.LiveBoardProvider


class CrossSourceLiveBoardProvider(_BaseLiveBoardProvider):
    """Cache board identity so a failed BK constituent call can use Sina labels."""

    def __init__(self, client: Any) -> None:
        super().__init__(client)
        self._boards: dict[tuple[str, str], dict[str, Any]] = {}

    def overview(self, board_type: str, target_date: date) -> list[dict[str, Any]]:
        rows = super().overview(board_type, target_date)
        for row in rows:
            key = (board_type, str(row.get("board_code") or ""))
            if key[1]:
                self._boards[key] = dict(row)
        return rows

    def constituents(
        self,
        board_type: str,
        board_code: str,
        target_date: date,
    ) -> list[dict[str, Any]]:
        board = self._boards.get((board_type, board_code), {})
        return fetch_board_constituents(
            self.client,
            board_code,
            board_type=board_type,
            board_name=str(board.get("board_name") or ""),
            target_date=target_date,
        )


# build_sector_review resolves this module global at call time. Replace it once
# so production, manual runs and smoke tests share the same fallback behavior.
_base.LiveBoardProvider = CrossSourceLiveBoardProvider
build_sector_review = _base.build_sector_review

__all__ = ["CrossSourceLiveBoardProvider", "build_sector_review"]
