from ashare_review.config import load_universe


def test_universe_has_exactly_17_unique_codes() -> None:
    stocks = load_universe("config/universe.yml")
    assert len(stocks) == 17
    assert len({stock.code for stock in stocks}) == 17
    assert stocks[0].code == "601138"
