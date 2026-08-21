from __future__ import annotations

from datetime import date

from ashare_review.config import StockConfig
from ashare_review.data import StockBundle, _append_completed_bar
from ashare_review.enhanced_data import (
    ResilientLiveDataSource,
    _completed_intraday,
    _fill_daily_quote_fields,
)

_INTRADAY_SOURCES = ("东方财富60分钟", "腾讯60分钟", "新浪60分钟")
_DAILY_SOURCES = ("东方财富日线", "腾讯日线", "网易日线")


def _intraday_source(bundle: StockBundle) -> str:
    for source in reversed(bundle.core_sources):
        if source in _INTRADAY_SOURCES:
            return source
    # If the resilient fallback did not add a source, the frame came from the
    # base Eastmoney loader. The completed-frame guard below still verifies it.
    return "东方财富60分钟"


def _historical_daily_source(bundle: StockBundle) -> str:
    for status in bundle.source_status:
        source = str(status.get("source") or "")
        if source in _DAILY_SOURCES and status.get("ok"):
            return source
    return "历史日线"


def _append_source_once(bundle: StockBundle, source: str) -> None:
    if source not in bundle.core_sources:
        bundle.core_sources.append(source)


def _synthesize_completed_daily(bundle: StockBundle, target_date: date) -> bool:
    if bundle.valid_for_target:
        return True

    quote = bundle.quote
    if (
        quote is None
        or quote.data_date != target_date
        or quote.close is None
        or not _completed_intraday(bundle.intraday_60m, target_date)
    ):
        return False

    intraday_source = _intraday_source(bundle)
    combined = _append_completed_bar(
        bundle.daily,
        bundle.intraday_60m,
        quote,
        target_date,
    )
    last_date = None if combined.empty else combined["date"].max().date()
    valid = bool(not combined.empty and len(combined) >= 220 and last_date == target_date)
    if not valid:
        bundle.source_status.append(
            {
                "source": "完成日线合成",
                "ok": False,
                "date": target_date.isoformat(),
                "basis": [intraday_source, quote.source],
                "error": "未通过0.3%收盘价一致性校验或有效历史不足220日",
            }
        )
        return False

    bundle.daily = combined
    bundle.last_data_date = target_date
    bundle.valid_for_target = True
    same_provider = intraday_source == "腾讯60分钟" and quote.source == "腾讯行情"
    bundle.data_confidence = "medium" if same_provider else "high"

    historical_source = _historical_daily_source(bundle)
    composite_source = f"{historical_source}+{intraday_source}+{quote.source}合成完成日线"
    _append_source_once(bundle, composite_source)
    _fill_daily_quote_fields(bundle, target_date)
    bundle.source_status.append(
        {
            "source": "完成日线合成",
            "ok": True,
            "date": target_date.isoformat(),
            "basis": [historical_source, intraday_source, quote.source],
            "confidence": bundle.data_confidence,
            "same_provider_close_confirmation": same_provider,
        }
    )
    return True


class CompletedDailyLiveDataSource(ResilientLiveDataSource):
    """Confirm a completed daily bar after resilient intraday fallback.

    The target-date bar is synthesized only when a target-date close quote and
    a completed 15:00 intraday series agree within the existing 0.3% guard.
    Previous-day history alone is never relabelled as current-day data.
    """

    def load_stock(self, config: StockConfig, target_date: date) -> StockBundle:
        bundle = super().load_stock(config, target_date)
        _synthesize_completed_daily(bundle, target_date)
        return bundle
