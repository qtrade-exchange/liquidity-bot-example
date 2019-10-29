import sys
import requests
import yaml
import json

import logging as log
from decimal import Decimal
from pprint import pprint

from qtrade_client.api import QtradeAPI

COIN = Decimal('.00000001')

class APIScraper:
    def __init__(self, **kwargs):
        self.__dict__.update(**kwargs)
        #self.does_pull_orders = True # this shouldn't be required anymore

    def scrape_ticker(self):  # dummy function, meant to be overridden
        pass


class QTradeScraper(APIScraper):
    def __init__(self, **kwargs):
        self.api = QtradeAPI("https://api.qtrade.io", key=open("lpbot_hmac.txt", "r").read().strip())
        super().__init__(**kwargs)

    def scrape_ticker(self):
        tickers = {}
        for market, qmarket in self.markets.items():
            res = self.api.get("/v1/ticker/{}".format(market))

            log.debug("Ticker %s from %s was acquired successfully", market, self.exchange_name)
            bid = Decimal(res["bid"]).quantize(COIN)
            log.debug("Bid price is %s", bid)
            last = Decimal(res["last"]).quantize(COIN)
            log.debug("Last price is %s", last)
            ask = Decimal(res["ask"]).quantize(COIN)
            log.debug("Ask price is %s", ask)
            tickers[qmarket] = {"bid": bid, "last": last, "ask": ask}
        return tickers


class BittrexScraper(APIScraper):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def scrape_ticker(self):
        tickers = {}
        for market, qmarket in self.markets.items():
            res = json.loads(requests.get('https://api.bittrex.com/api/v1.1/public/getticker?market=' + market).content)

            if not res['success']:
                log.warning("Could not acquire ticker %s from %s", market, self.exchange_name)
                return

            log.debug("Ticker %s from %s was acquired successfully", market, self.exchange_name)
            bid = Decimal(res["result"]["Bid"]).quantize(COIN)
            log.debug("Bid price is %s", bid)
            last = Decimal(res["result"]["Last"]).quantize(COIN)
            log.debug("Last price is %s", last)
            ask = Decimal(res["result"]["Ask"]).quantize(COIN)
            log.debug("Ask price is %s", ask)
            tickers[qmarket] = {"bid": bid, "last": last, "ask": ask}
        return tickers


if __name__ == "__main__":
    log_level = log.DEBUG

    root = log.getLogger()
    root.setLevel(log_level)

    handler = log.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    formatter = log.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root.addHandler(handler)

    config = yaml.load(open('config.yml'))['market_data_collector']

    pprint(BittrexScraper(exchange_name='bittrex', markets=config['scrapers']['bittrex']['markets']).scrape_ticker())
    pprint(QTradeScraper(exchange_name='qtrade', markets=config['scrapers']['qtrade']['markets']).scrape_ticker())
