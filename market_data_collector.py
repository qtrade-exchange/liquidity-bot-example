import threading, sys, json, time, yaml, asyncio
import logging as log

from data_classes import MarketDatastore, OrderDatastore
from market_scrapers import qTradeScraper

class MarketDataCollector:
	def __init__(self):
		# load config from yaml file
		self.config = yaml.load(open("market_data_collector_config.yml"))
		# load scrapers
		self.scrapers = [qTradeScraper()]

	def update_tickers(self):
		log.debug("Updating tickers...")
		for s in self.scrapers:
			MarketDatastore.tickers[s.market_name] = s.scrape_ticker()


	def update_midpoints(self): # be sure to update tickers first
		log.debug("Updating midpoints...")
		for m in MarketDatastore.tickers:
			bid = MarketDatastore.tickers[m]["bid"]
			last = MarketDatastore.tickers[m]["last"]
			MarketDatastore.midpoints[m] = (bid+last)/2

	def update_balances(self):
		log.debug("Updating balances...")
		for s in self.scrapers:
			bs = s.scrape_balances()
			for b in bs:
				MarketDatastore.balances[b["currency"]] = b["balance"]

	def update_orders(self):
		log.debug("Updating orders...")
		for s in self.scrapers:
			orders = s.scrape_orders()
			OrderDatastore.buy_orders[s.market_name] = orders["buy_orders"]
			OrderDatastore.sell_orders[s.market_name] = orders["sell_orders"]

		print(OrderDatastore.buy_orders)
		print(OrderDatastore.sell_orders)

		# find and log the number of active buy and sell orders
		OrderDatastore.num_active_buy = 0
		OrderDatastore.num_active_sell = 0

		for o in OrderDatastore.buy_orders.values():
			OrderDatastore.num_active_buy += len(o)
		for o in OrderDatastore.sell_orders.values():
			OrderDatastore.num_active_sell += len(o)

		log.info("%s active buy orders", OrderDatastore.num_active_buy)
		log.info("%s active sell orders", OrderDatastore.num_active_sell)

	async def daemon(self):
		while True:
			log.info("Pulling market data...")
			self.update_tickers()
			self.update_midpoints()
			self.update_balances()
			self.update_orders()
			await asyncio.sleep(self.config["update_period"])


if __name__ == "__main__":
	# set up logging
	log_level = log.INFO
	root = log.getLogger()
	root.setLevel(log_level)
	handler = log.StreamHandler(sys.stdout)
	handler.setLevel(log_level)
	formatter = log.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
	handler.setFormatter(formatter)
	root.addHandler(handler)

	asyncio.run(MarketDataCollector().daemon())