from ashare_review.config import load_universe


def test_universe_contains_the_confirmed_59_stock_monitoring_pool() -> None:
    stocks = load_universe("config/universe.yml")
    assert len(stocks) == 59
    assert len({stock.code for stock in stocks}) == 59
    assert stocks[0].code == "601138"
    assert {
        "002475",
        "603993",
        "688396",
        "600030",
        "600941",
        "600031",
    }.issubset({stock.code for stock in stocks})
