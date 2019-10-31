import asyncio
import logging

from data_classes import ExchangeDatastore, PrivateDatastore
from market_scrapers import QTradeScraper, BittrexScraper

scraper_classes = {
    "qtrade": QTradeScraper,
    "bittrex": BittrexScraper
}

log = logging.getLogger('mdc')


class MarketDataCollector:

    def __init__(self, config):
        # load config from yaml file
        self.config = config
        # load scrapers
        self.scrapers = []
        for name, cfg in self.config['scrapers'].items():
            self.scrapers.append(
                scraper_classes[name](exchange_name=name, **cfg))

    def update_tickers(self):
        log.debug("Updating tickers...")
        for s in self.scrapers:
            ExchangeDatastore.tickers[s.exchange_name] = s.scrape_ticker()

    def update_midpoints(self):  # be sure to update tickers first
        log.debug("Updating midpoints...")
        for exchange_name, markets in ExchangeDatastore.tickers.items():
            for market, ticker in markets.items():
                bid = ticker["bid"]
                last = ticker["last"]
                ExchangeDatastore.midpoints.setdefault(exchange_name, {})
                ExchangeDatastore.midpoints[exchange_name][
                    market] = (bid + last) / 2

    async def daemon(self):
        log.info("Starting market data collector; interval period %s sec",
                 self.config['update_period'])
        while True:
            try:
                log.info("Pulling market data...")
                self.update_tickers()
                self.update_midpoints()
                await asyncio.sleep(self.config["update_period"])
            except Exception:
                log.warning("Market scraper loop exploded", exc_info=True)
