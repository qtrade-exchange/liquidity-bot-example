import threading, sys, requests, json
import logging as log
from decimal import Decimal
import time

from price_finder import PriceFinder


class GenericOrder:
	def __init__(self, doge_value, btc_value):
		if type(doge_value) != Decimal or type(btc_value) != Decimal:
			raise TypeError("Currency values for orders MUST be Decimal type.")
		self.doge_value = doge_value
		self.btc_value = btc_value


class BuyOrder(GenericOrder): # buying Doge
	def __init__(self, doge_value, btc_value):
		super().__init__(doge_value, btc_value)


class SellOrder(GenericOrder): # selling Doge
	def __init__(self, doge_value, btc_value):
		super().__init__(doge_value, btc_value)


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
		self.orders = []

		# get our inventory size


	def create_orders(self):
		self.update_midpoint()


	def update_midpoint(self):
		log.info("Updating OrderPlacer's midpoint...")
		with self.price_finder._lock:
			log.debug("PriceFinder locked by OrderPlacer to update midpoint")
			self.midpoint = self.price_finder.avg_midpoint
			log.debug("Unlocking PriceFinder")


if __name__ == "__main__":
	log_level = log.INFO

	root = log.getLogger()
	root.setLevel(log_level)

	handler = log.StreamHandler(sys.stdout)
	handler.setLevel(log_level)
	formatter = log.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
	handler.setFormatter(formatter)
	root.addHandler(handler)

#	op = OrderPlacer()
#	time.sleep(4)
#	op.update_midpoint()
#	print(op.midpoint)
	GenericOrder(Decimal(1), Decimal(2))