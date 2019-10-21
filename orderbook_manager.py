import threading, sys, json, time, yaml, asyncio
import logging as log

from data_classes import ExchangeDatastore, PrivateDatastore
from market_scrapers import qTradeScraper
from qtrade_client.api import QtradeAPI

class OrderbookManager:
	def __init__(self):
		# load config from yaml file
		self.config = yaml.load(open("orderbook_manager_config.yml"))
		self.api = QtradeAPI("https://api.qtrade.io", key=open("lpbot_hmac.txt", "r").read().strip())

	def rebalance_orders(self):
		#self.cancel_all_orders()
		# create new orders
		alloc = self.config['allocations']
		for coin in alloc:
			if coin == 'BTC':
				# set buy orders using BTC
				allocation_sum = 0
				num_markets = 0
				# sum all market coin allocations
				for market_coin in alloc[coin]:
					if market_coin not in {'reserve', 'target'}:
						allocation_sum += alloc[coin][market_coin]
						num_markets += 1
				amount_to_allocate = min(min(alloc[coin]['target'], allocation_sum), PrivateDatastore.balances[coin]-alloc['reserve'])
				print(amount_to_allocate)
				# evenly distribute amount_to_allocate among all allocated coins and place orders
				for market_coin in alloc[coin]:
					if market_coin not in {'reserve', 'target'}:
						total_base_amount = amount_to_allocate/num_markets
						# find the price point distributions based on the midpoint and config
						# then place the orders
			else:
				# set sell orders using other coins
				market_name = coin + "_BTC"
				

	def cancel_all_orders(self):
		for order in PrivateDatastore.buy_orders['qtrade'] + PrivateDatastore.sell_orders['qtrade']:
			log.debug("Cancelling order %s", order['id'])
			self.api.post("https://api.qtrade.io/v1/user/cancel_order", json={"id":order['id']})

	def place_order(self):
		pass

	def check_coin_allocations(self, coin):
		current_allocs = dict()
		for m in PrivateDatastore.buy_orders.values(): # for each market
			for bo in m: # for each buy order on that market
				if bo['base_currency'] == coin:
					try:
						current_allocs[bo['market_currency']] += bo['base_amount']
					except KeyError:
						current_allocs[bo['market_currency']] = bo['base_amount']
		for m in PrivateDatastore.sell_orders.values():
			for so in m:
				if so['market_currency'] == coin:
					try:
						current_allocs[so['base_currency']] += so['amount']
					except KeyError:
						current_allocs[so['base_currency']] = so['amount']
		log.info("%s current allocations: %s", coin, current_allocs)
		for m_coin in current_allocs:
			if current_allocs[m_coin] > self.config['allocations'][coin][m_coin]:
				return True # trigger a rebalance
		return False

	def check_coin_reserve(self, coin):
		if PrivateDatastore.balances[coin] < self.config['allocations'][coin]['reserve']:
			return True # trigger a rebalance
		return False

	def buy_sell_bias(self):
		return (.5, .5)

	async def monitor(self):
		while True:
			log.info("Monitoring market data...")
			self.rebalance_orders()
			#for coin in self.config['allocations']:
			#	if self.check_coin_allocations(coin) or self.check_coin_reserve(coin):
			#		self.rebalance_orders()
			#		break
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

	OrderbookManager().rebalance_orders()
