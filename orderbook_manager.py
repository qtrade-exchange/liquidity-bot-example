import threading, sys, json, time, yaml, asyncio
import logging as log

from data_classes import MarketDatastore, OrderDatastore
from market_scrapers import qTradeScraper

class OrderbookManager:
	def __init__(self):
		# load config from yaml file
		self.config = yaml.load(open("orderbook_manager_config.yml"))

	def rebalance_orders(self):
		pass

	def check_coin_allocations(self, coin):
		current_allocs = dict()
		for m in OrderDatastore.buy_orders.values(): # for each market
			for bo in m: # for each buy order on that market
				if bo['base_currency'] == coin:
					try:
						current_allocs[bo['market_currency']] += bo['base_amount']
					except KeyError:
						current_allocs[bo['market_currency']] = bo['base_amount']
		for m_coin in current_allocs:
			if current_allocs[m_coin] > self.config['allocations'][coin][m_coin]:
				# trigger a rebalance
				pass
		print(current_allocs.values())

	def buy_sell_bias(self):
		return (.5, .5)

	async def monitor(self):
		while True:
			log.info("Monitoring market data...")
			self.check_coin_allocations('BTC')
			await asyncio.sleep(self.config['monitor_period'])


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

	asyncio.run(OrderbookManager().monitor())