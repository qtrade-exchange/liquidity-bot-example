import threading, sys, json, time, yaml, asyncio
import logging as log
from decimal import Decimal

from data_classes import ExchangeDatastore, PrivateDatastore
from market_scrapers import QTradeScraper
from qtrade_client.api import QtradeAPI

COIN = Decimal('.00000001')

class OrderbookManager:
	def __init__(self):
		# load config from yaml file
		self.config = yaml.load(open("orderbook_manager_config.yml"))
		self.api = QtradeAPI("https://api.qtrade.io", key=open("lpbot_hmac.txt", "r").read().strip())

	def rebalance_orders(self):
		self.cancel_all_orders()
		log.info("Placing new orders...")
		alloc = self.config['allocations']
		base_coin = "BTC"
		for coin in alloc:
			if PrivateDatastore.balances[coin] < Decimal(alloc[coin]['reserve']):
				log.warning("%s balance is below reserve...", coin)
				continue
			if coin == base_coin:
				# set buy orders using BTC
				allocation_sum = 0
				num_markets = 0
				# sum all market coin allocations
				for market_coin in alloc[coin]:
					if market_coin not in {'reserve', 'target'}:
						allocation_sum += alloc[coin][market_coin]
						num_markets += 1
				amount_to_allocate = min(min(alloc[coin]['target'], allocation_sum), PrivateDatastore.balances[coin]-Decimal(alloc[coin]['reserve']))
				# evenly distribute amount_to_allocate among all allocated coins and place orders
				for market_coin in alloc[coin]:
					if market_coin not in {'reserve', 'target'}:
						market_name = market_coin + "_" + coin
						for i in self.config['intervals']['buy']:
							price = ExchangeDatastore.midpoints['qtrade'][market_name]
							price = price - Decimal(i) * price
							buy_amount = amount_to_allocate/num_markets*Decimal(self.config['intervals']['buy'][i])/price
							log.info("Buying %s %s for %s %s each", buy_amount.quantize(COIN), market_coin, price.quantize(COIN), coin)
							req = {'amount':str(buy_amount.quantize(COIN)), 'price':str(price.quantize(COIN)), 'market_id':PrivateDatastore.qtrade_market_map[market_name]['id']}
							self.api.post('/v1/user/buy_limit', json=req)
			else:
				# set sell orders using other coins
				market_name = coin + "_" + base_coin
				amount_to_allocate = min(min(alloc[coin][base_coin], alloc[coin]['target']), PrivateDatastore.balances[coin]-Decimal(alloc[coin]['reserve']))
				for i in self.config['intervals']['sell']:
					price = ExchangeDatastore.midpoints['qtrade'][market_name]
					price = price - Decimal(i) * price
					amount = amount_to_allocate*Decimal(self.config['intervals']['sell'][i])
					req = {'amount':str(amount.quantize(COIN)), 'price':str(price.quantize(COIN)), 'market_id':PrivateDatastore.qtrade_market_map[market_name]['id']}
					self.api.post('/v1/user/sell_limit', json=req)

	def cancel_all_orders(self):
		log.info("Cancelling all orders...")
		for bo in PrivateDatastore.buy_orders['qtrade']:
			log.debug("Cancelling order %s", bo['id'])
			PrivateDatastore.balances[bo['base_currency']] += bo['base_amount']
			self.api.post("https://api.qtrade.io/v1/user/cancel_order", json={"id":bo['id']})
		for so in PrivateDatastore.sell_orders['qtrade']:
			log.debug("Cancelling order %s", so['id'])
			PrivateDatastore.balances[so['market_currency']] += so['amount']
			self.api.post("https://api.qtrade.io/v1/user/cancel_order", json={"id":so['id']})

	# this function duplicates some behavior in check_placed_orders, plan to remove
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
		bal = PrivateDatastore.balances[coin]
		res = Decimal(self.config['allocations'][coin]['reserve'])
		if (res - bal)/res > self.config['reserve_margin']:
			log.info("Not enough %s in reserve!", coin)
			return True # trigger a rebalance
		return False

	def check_placed_orders(self, coin):
		if coin == 'BTC':
			if not PrivateDatastore.buy_orders['qtrade']:
				log.info("There are currently no buy orders!")
				return True
			total_allocated = 0
			market_allocated = dict() # allocated BTC to buy each coin
			num_buy_orders = dict() # number of buy orders per coin
			for bo in PrivateDatastore.buy_orders['qtrade']:
				market_allocated[bo['market_currency']] = market_allocated.setdefault(bo['market_currency'], Decimal(0)) + bo['base_amount']
				total_allocated += bo['base_amount']
				num_buy_orders[bo['market_currency']] = num_buy_orders.setdefault(bo['market_currency'], Decimal(0)) + 1
			if total_allocated > self.config['allocations'][coin]['target']:
				log.info("Too much %s allocated to buy other coins!", coin)
				return True
			if {x for x in set(num_buy_orders.values()) if x != len(self.config['intervals']['buy'])}:
				log.info("Not enough buy orders currently on the market!")
				return True
			for market_coin in market_allocated:
				if market_allocated[market_coin] > self.config['allocations'][coin][market_coin]:
					log.info("Too much %s allocated to buy %s!", coin, market_coin)
					return True
		else:
			base_coin = 'BTC'
			if not PrivateDatastore.sell_orders['qtrade']:
				log.info("There are currently no sell orders!")
				return True
			total_allocated = 0
			num_sell_orders = 0
			for so in PrivateDatastore.sell_orders['qtrade']:
				if so['market_coin'] == coin:
					total_allocated += so['amount']
					num_sell_orders += 1
			if total_allocated > self.config['allocations'][base_coin]:
				log.info("Selling too much %s for %s!", coin, base_coin)
				return True
			if num_sell_orders != len(self.config['intervals']['buy']):
				log.info("Not enough %s sell orders currently on the market!", coin)
				return True
		return False

	def buy_sell_bias(self):
		return (.5, .5)

	async def monitor(self):
		while True:
			log.info("Monitoring market data...")
			for coin in self.config['allocations']:
				if self.check_coin_allocations(coin) or self.check_coin_reserve(coin) or self.check_placed_orders(coin):
					self.rebalance_orders()
					break
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
