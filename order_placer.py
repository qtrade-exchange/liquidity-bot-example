import threading, sys, requests, json
import logging as log
from decimal import Decimal
import time
from pprint import pprint

from price_finder import PriceFinder
from qtrade_client.api import QtradeAPI

COIN = Decimal('.00000001')


class GenericOrder:
	def __init__(self, amount, price, active = False, order_id = None):
		self.amount = Decimal(amount)
		self.price = Decimal(price)
		self.active = active
		self.order_id = order_id

	def __repr__(self):
		return "Order for {} DOGE at {} BTC each".format(self.amount, self.price)


class BuyOrder(GenericOrder): # buying Doge
	def __repr__(self):
		return "Buy order for {} DOGE at {} BTC each".format(self.amount, self.price)


class SellOrder(GenericOrder): # selling Doge
	def __repr__(self):
		return "Sell order for {} DOGE at {} BTC each".format(self.amount, self.price)


class OrderPlacer:
	def __init__(self, doge_inv = 0, btc_inv = 0, order_intervals = {.02:.2, .04:.5, .05:.3}, difference_threshold = .1, update_interval = 2):
		self._lock = threading.Lock()
		self.doge_inv = Decimal(doge_inv)
		self.btc_inv = Decimal(btc_inv)
		self.difference_threshold = difference_threshold
		self.update_interval = update_interval
		self.order_intervals = dict()
		# ensure all order_intervals keys and values are decimal
		for k in order_intervals: # keys are slippage and values are ratio of inventory
			self.order_intervals[Decimal(k)] = Decimal(order_intervals[k])
		self.midpoint = None
		self.price_finder = PriceFinder()
		self.buy_orders = []
		self.sell_orders = []
		self.api = QtradeAPI("https://api.qtrade.io", key=open("lpbot_hmac.txt", "r").read().strip())

	def fetch_balances(self):
		log.debug("Fetching balances from api...")
		res = self.api.get('/v1/user/balances')['balances']
		for r in res:
			if r["currency"] == "BTC":
				self.btc_inv = Decimal(r["balance"])
			elif r["currency"] == "DOGE":
				self.doge_inv = Decimal(r["balance"])
		log.info("Current inventory is %s BTC and %s DOGE", self.btc_inv, self.doge_inv)

	def orders_daemon(self):
		while True:
			self.fetch_orders()
			self.fetch_balances()
			self.create_orders()
			time.sleep(self.update_interval)

	def fetch_orders(self): # fetch orders currently in place
		log.debug("Fetching active orders from api...")
		fetched_buy_orders = []
		fetched_sell_orders = []
		fetched_orders = self.api.get("https://api.qtrade.io/v1/user/orders")['orders']
		for o in fetched_orders:
			if o["open"]:
				if o["order_type"] == "buy_limit":
					fetched_buy_orders.append(BuyOrder(o["market_amount_remaining"], o["price"], True, o["id"]))
				elif o["order_type"] == "sell_limit":
					fetched_sell_orders.append(SellOrder(o["market_amount_remaining"], o["price"], True, o["id"]))
		self.buy_orders = fetched_buy_orders
		self.sell_orders = fetched_sell_orders
		log.info("Fetched %s active orders!", len(fetched_buy_orders)+len(fetched_sell_orders))

	def create_orders(self): # create new orders, compare them to the ones currently in place
		self.update_midpoint()
		new_buy_orders = []
		new_sell_orders = []
		log.debug("Generating new orders...")
		for i in self.order_intervals:
			amount_mult = self.order_intervals[i]
			buy_amount = (self.btc_inv*amount_mult/self.midpoint).quantize(COIN)
			buy_price = (self.midpoint-i*self.midpoint).quantize(COIN)
			sell_amount = (self.doge_inv*amount_mult).quantize(COIN)
			sell_price = (self.midpoint+i*self.midpoint).quantize(COIN)
			new_buy_orders.append(BuyOrder(buy_amount, buy_price))
			new_sell_orders.append(SellOrder(sell_amount, sell_price))
		log.debug("Generated new orders!")
		if self.eval_orders(new_buy_orders, new_sell_orders):
			self.cancel_orders()
			self.buy_orders = new_buy_orders
			self.sell_orders = new_sell_orders
			self.place_orders()

	def eval_orders(self, new_buy_orders, new_sell_orders): # determine if we need to cancel the old orders and place new ones
		if len(self.buy_orders) != len(new_buy_orders) or len(self.sell_orders) != len(new_sell_orders):
			return True
		# find the largest percent difference in price between new and old orders
		max_percent_diff = 0
		for i in range(len(self.buy_orders)):
			percent_diff = abs(self.buy_orders[i].price-new_buy_orders[i].price)/self.buy_orders[i].price
			max_percent_diff = max(max_percent_diff, percent_diff)
		for i in range(len(self.sell_orders)):
			percent_diff = abs(self.sell_orders[i].price-new_sell_orders[i].price)/self.sell_orders[i].price
			max_percent_diff = max(max_percent_diff, percent_diff)
		if max_percent_diff > self.difference_threshold:
			return True
		return False

	def update_midpoint(self):
		log.info("Updating OrderPlacer's midpoint...")
		with self.price_finder._lock:
			log.debug("PriceFinder locked by OrderPlacer to update midpoint")
			self.midpoint = self.price_finder.avg_midpoint
			log.debug("Unlocking PriceFinder")

	def place_orders(self):
		log.info("Placing new orders...")
		for b in self.buy_orders:
			log.info("Placing %s", b)
			req = {'amount': str(b.amount), 'market_id': 36, 'price': str(b.price)}
			self.api.post("https://api.qtrade.io/v1/user/buy_limit", json=req)
			b.active = True
		for s in self.sell_orders:
			log.info("Placing %s", s)
			req = {'amount': str(s.amount), 'market_id': 36, 'price': str(s.price)}
			self.api.post("https://api.qtrade.io/v1/user/sell_limit", json=req)
			s.active = False

	def cancel_orders(self):
		log.info("Cancelling all orders...")
		for o in self.buy_orders+self.sell_orders:
			if o.active:
				log.debug("Cancelling order %s", o.order_id)
				if self.api.post("https://api.qtrade.io/v1/user/cancel_order", json={"id":o.order_id}):
					log.info("Cancelled order %s", o.order_id)
				else:
					log.warning("Could not cancel order %s", o.order_id)


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
	op.orders_daemon()