import sys
import requests
import yaml
import json
import ccxt

import logging as log
from decimal import Decimal
from pprint import pprint

from qtrade_client.api import QtradeAPI

COIN = Decimal('.00000001')


class APIScraper:

    def __init__(self, **kwargs):
        self.__dict__.update(**kwargs)

    def scrape_ticker(self):  # dummy function, meant to be overridden
        pass


class QTradeScraper(APIScraper):

    def __init__(self, **kwargs):
        self.api = QtradeAPI("https://api.qtrade.io",
                             key=open("lpbot_hmac.txt", "r").read().strip())
        super().__init__(**kwargs)

    def scrape_ticker(self):
        tickers = {}
        for market, qmarket in self.markets.items():
            res = self.api.get("/v1/ticker/{}".format(market))

            log.debug("Ticker %s from %s was acquired successfully",
                      market, self.exchange_name)
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
            res = json.loads(requests.get(
                'https://api.bittrex.com/api/v1.1/public/getticker?market=' + market).content)

            if not res['success']:
                log.warning("Could not acquire ticker %s from %s",
                            market, self.exchange_name)
                return

            log.debug("Ticker %s from %s was acquired successfully",
                      market, self.exchange_name)
            bid = Decimal(res["result"]["Bid"]).quantize(COIN)
            log.debug("Bid price is %s", bid)
            last = Decimal(res["result"]["Last"]).quantize(COIN)
            log.debug("Last price is %s", last)
            ask = Decimal(res["result"]["Ask"]).quantize(COIN)
            log.debug("Ask price is %s", ask)
            tickers[qmarket] = {"bid": bid, "last": last, "ask": ask}
        return tickers


class CCXTScraper(APIScraper):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def scrape_ticker(self):
        tickers = {}
        for market, qmarket in self.markets.items():
            bid_total = Decimal('0')
            last_total = Decimal('0')
            ask_total = Decimal('0')
            for ex_id in self.exchanges:
                res = ex_class = getattr(ccxt, ex_id)
                ex = ex_class({
                    'apiKey': '',
                    'secret': '',
                    'timeout': 30000,
                    'enableRateLimit': True,
                })
                res = ex.fetchTicker(market)
                log.debug("Ticker %s from %s was acquired successfully",
                          market, ex_id)
                bid_total += Decimal(res['bid'])
                last_total += Decimal(res['last'])
                ask_total += Decimal(res['ask'])
            bid_total = (bid_total/len(self.exchanges)).quantize(COIN)
            last_total = (last_total/len(self.exchanges)).quantize(COIN)
            ask_total = (ask_total/len(self.exchanges)).quantize(COIN)
            tickers[qmarket] = {"bid": bid_total, "last": last_total, "ask": ask_total}
        return tickers


if __name__ == "__main__":
    log_level = log.INFO

    root = log.getLogger()
    root.setLevel(log_level)

    handler = log.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    formatter = log.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root.addHandler(handler)

    config = yaml.load(open('config.yml'))['market_data_collector']

    pprint(BittrexScraper(exchange_name='bittrex', markets=config[
           'scrapers']['bittrex']['markets']).scrape_ticker())
    pprint(QTradeScraper(exchange_name='qtrade', markets=config[
           'scrapers']['qtrade']['markets']).scrape_ticker())

    pprint(CCXTScraper(markets=config['scrapers']['ccxt']['markets'],
            exchanges=config['scrapers']['ccxt']['exchanges']).scrape_ticker())
