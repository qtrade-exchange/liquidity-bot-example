import sys
import logging as log
from decimal import Decimal

from qtrade_client.api import QtradeAPI


class APIScraper:
    def __init__(self, **kwargs):
        self.__dict__.update(**kwargs)
        self.does_pull_orders = True

    def scrape_ticker(self):  # dummy function, meant to be overridden
        pass


class QTradeScraper(APIScraper):
    def __init__(self, **kwargs):
        self.api = QtradeAPI("https://api.qtrade.io", key=open("lpbot_hmac.txt", "r").read().strip())
        super().__init__(**kwargs)

    def scrape_ticker(self):
        tickers = {}
        for market in self.markets:
            res = self.api.get("/v1/ticker/{}".format(market))

            log.debug("Ticker %s from %s was acquired successfully", market, self.market_name)
            bid = Decimal(res["bid"])
            log.debug("Bid price is %s", bid)
            last = Decimal(res["last"])
            log.debug("Last price is %s", last)
            ask = Decimal(res["ask"])
            log.debug("Ask price is %s", ask)
            tickers[market] = {"bid": bid, "last": last, "ask": ask}
        return tickers


if __name__ == "__main__":
    log_level = log.INFO

    root = log.getLogger()
    root.setLevel(log_level)

    handler = log.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    formatter = log.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root.addHandler(handler)

    QTradeScraper()
