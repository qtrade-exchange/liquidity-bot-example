import asyncio
import logging

from data_classes import ExchangeDatastore, PrivateDatastore
from market_scrapers import QTradeScraper

scraper_classes = {
    "qtrade": QTradeScraper,
}

log = logging.getLogger('mdc')


class MarketDataCollector:
    def __init__(self, config):
        # load config from yaml file
        self.config = config
        # load scrapers
        self.scrapers = []
        for name, cfg in self.config['scrapers'].items():
            self.scrapers.append(scraper_classes[name](market_name=name, **cfg))
        PrivateDatastore.qtrade_market_map = QTradeScraper().market_map  # this is a hack and should probably be replaced

    def update_tickers(self):
        log.debug("Updating tickers...")
        for s in self.scrapers:
            ExchangeDatastore.tickers[s.market_name] = s.scrape_ticker()

    def update_midpoints(self):  # be sure to update tickers first
        log.debug("Updating midpoints...")
        for exchange_name, markets in ExchangeDatastore.tickers.items():
            for market, ticker in markets.items():
                bid = ticker["bid"]
                last = ticker["last"]
                ExchangeDatastore.midpoints.setdefault(exchange_name, {})
                ExchangeDatastore.midpoints[exchange_name][market] = (bid + last) / 2

    def update_balances(self):
        log.debug("Updating balances...")
        for s in self.scrapers:
            bs = s.scrape_balances()
            for b in bs:
                PrivateDatastore.balances[b["currency"]] = b["balance"]
                log.debug("%s balance is %s", b['currency'], b['balance'])

    def update_orders(self):
        log.debug("Updating orders...")
        for s in self.scrapers:
            if not s.does_pull_orders:
                continue
            orders = s.scrape_orders()
            PrivateDatastore.buy_orders[s.market_name] = orders["buy_orders"]
            PrivateDatastore.sell_orders[s.market_name] = orders["sell_orders"]

        log.debug("Active buy orders: %s", PrivateDatastore.buy_orders)
        log.debug("Active sell orders: %s", PrivateDatastore.sell_orders)

        # find and log the number of active buy and sell orders
        num_active_buy = 0
        num_active_sell = 0

        for o in PrivateDatastore.buy_orders.values():
            num_active_buy += len(o)
        for o in PrivateDatastore.sell_orders.values():
            num_active_sell += len(o)

        log.info("%s active buy orders", num_active_buy)
        log.info("%s active sell orders", num_active_sell)

    async def daemon(self):
        while True:
            log.info("Pulling market data...")
            self.update_tickers()
            self.update_midpoints()
            self.update_balances()
            self.update_orders()
            await asyncio.sleep(self.config["update_period"])
