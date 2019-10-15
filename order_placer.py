import threading, sys, requests, json
import logging as log
from decimal import Decimal
import time

from price_finder import PriceFinder
from qtrade_auth import QtradeAuth

COIN = Decimal('.00000001')


class GenericOrder:
	def __init__(self, amount, price, active = False):
		if type(amount) != Decimal or type(price) != Decimal:
			raise TypeError("Currency values for orders MUST be Decimal type.")
		self.amount = amount
		self.price = price
		self.active = active

	def __repr__(self):
		return "Order for {} DOGE at {} BTC each.".format(self.amount, self.price)


class BuyOrder(GenericOrder): # buying Doge
	def __init__(self, amount, price):
		super().__init__(amount, price)

	def __repr__(self):
		return "Buy order for {} DOGE at {} BTC each.".format(self.amount, self.price)


class SellOrder(GenericOrder): # selling Doge
	def __init__(self, amount, price):
		super().__init__(amount, price)

	def __repr__(self):
		return "Sell order for {} DOGE at {} BTC each.".format(self.amount, self.price)


class OrderPlacer:
	def __init__(self, doge_inv = 0, btc_inv = 0, order_intervals = {.02:.2, .04:.5, .05:.3}):
		self._lock = threading.Lock()
		self.doge_inv = Decimal(doge_inv)
		self.btc_inv = Decimal(btc_inv)
		self.order_intervals = dict()
		# ensure all order_intervals keys and values are decimal
		for k in order_intervals: # keys are slippage and values are ratio of inventory
			self.order_intervals[Decimal(k)] = Decimal(order_intervals[k])
		self.midpoint = None
		self.price_finder = PriceFinder()
		self.buy_orders = []
		self.sell_orders = []

		# get our inventory size
		self.api = requests.Session()

		self.api.auth = QtradeAuth(open("lpbot_hmac.txt", "r").read().strip())
		res = self.api.get('https://api.qtrade.io/v1/user/balances').json()['data']['balances']
		for r in res:
			if r["currency"] == "BTC":
				self.btc_inv = Decimal(r["balance"])
			elif r["currency"] == "DOGE":
				self.doge_inv = Decimal(r["balance"])
		log.info("Current inventory is %s BTC and %s DOGE", self.btc_inv, self.doge_inv)

	def create_orders(self):
		self.update_midpoint()
		for i in self.order_intervals:
			amount_mult = self.order_intervals[i]
			self.buy_orders.append(BuyOrder((self.btc_inv*amount_mult/self.midpoint).quantize(COIN), (self.midpoint-i*self.midpoint).quantize(COIN)))
			self.sell_orders.append(SellOrder((self.doge_inv*amount_mult).quantize(COIN), (self.midpoint+i*self.midpoint).quantize(COIN)))

	def update_midpoint(self):
		log.info("Updating OrderPlacer's midpoint...")
		with self.price_finder._lock:
			log.debug("PriceFinder locked by OrderPlacer to update midpoint")
			self.midpoint = self.price_finder.avg_midpoint
			log.debug("Unlocking PriceFinder")

	def place_orders(self):
		for b in self.buy_orders:
			log.info("Placing %s", b)
			req = {'amount': str(b.amount), 'market_id': 36, 'price': str(b.price)}
			self.api.post("https://api.qtrade.io/v1/user/buy_limit", json=req).json()
		for s in self.sell_orders:
			log.info("Placing %s", s)
			req = {'amount': str(s.amount), 'market_id': 36, 'price': str(s.price)}
			self.api.post("https://api.qtrade.io/v1/user/sell_limit", json=req).json()


if __name__ == "__main__":
	log_level = log.INFO

	root = log.getLogger()
	root.setLevel(log_level)

	handler = log.StreamHandler(sys.stdout)
	handler.setLevel(log_level)
	formatter = log.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
	handler.setFormatter(formatter)
	root.addHandler(handler)

	op = OrderPlacer()
	#time.sleep(4)
	op.create_orders()
	op.place_orders()