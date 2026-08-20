from __future__ import annotations

from ashare_review.config import StockConfig
from ashare_review.data import fetch_tencent_quote


class FakeClient:
    def get_text(self, url, *, params=None, encoding=None):
        fields = [""] * 50
        fields[1] = "工业富联"
        fields[3] = "62.15"
        fields[4] = "61.20"
        fields[5] = "61.50"
        fields[6] = "123456"
        fields[30] = "20260820150000"
        fields[32] = "1.55"
        fields[33] = "62.80"
        fields[34] = "61.10"
        fields[35] = "62.15/123456/765432100.00"
        fields[38] = "2.36"
        fields[39] = "28.4"
        fields[44] = "3500.0"
        fields[45] = "4200.0"
        fields[46] = "4.2"
        return 'v_sh601138="' + "~".join(fields) + '";'


def test_tencent_quote_parser_keeps_close_timestamp_and_units() -> None:
    config = StockConfig("601138", "工业富联", "SH", "消费电子", ("AI算力",), 90)
    quote = fetch_tencent_quote(FakeClient(), config)
    assert quote.close == 62.15
    assert quote.data_date.isoformat() == "2026-08-20"
    assert quote.volume == 12_345_600
    assert quote.amount == 765_432_100
    assert quote.turnover_rate == 2.36
