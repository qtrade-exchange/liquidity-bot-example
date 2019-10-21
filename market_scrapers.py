import threading, sys, json, time
import logging as log
from decimal import Decimal

from qtrade_client.api import QtradeAPI


class APIScraper:
	def __init__(self, **kwargs):
		self.__dict__.update(**kwargs)
		self.does_pull_orders = True

	def scrape_ticker(self): # dummy function, meant to be overridden
		pass


class qTradeScraper(APIScraper):
	def __init__(self, **kwargs):
		self.api = QtradeAPI("https://api.qtrade.io", key=open("lpbot_hmac.txt", "r").read().strip())
		super().__init__(**kwargs)

	def scrape_ticker(self):
		tickers = {}
		for market in self.markets:
			res = self.api.get("/v1/ticker/{}".format(market))

			log.debug("Ticker %s from %s was acquired successfully", market, self.market_name)
			bid = Decimal(res["bid"])
			log.debug("Bid price is %s", bid)
			last = Decimal(res["last"])
			log.debug("Last price is %s", last)
			ask = Decimal(res["ask"])
			log.debug("Ask price is %s", ask)
			tickers[market] = {"bid":bid, "last":last, "ask":ask}
		return tickers

	def scrape_balances(self):
		bs = self.api.get("/v1/user/balances")["balances"]

		log.debug("Balances from %s were acquired successfully", self.market_name)
		for b in bs:
			b['balance'] = Decimal(b['balance'])
		return bs

	def scrape_orders(self):
		orders = self.api.get("/v1/user/orders")["orders"]
		open_orders = {"buy_orders": [], "sell_orders": []}

		for o in orders:
			if o["open"]:
				mi = self.api.get("/v1/market/" + str(o['market_id']))['market']
				o['price'] = Decimal(o['price'])
				o['amount'] = Decimal(o['market_amount_remaining'])
				o['market_currency'] = mi['market_currency']
				o['base_currency'] = mi['base_currency']

				o['base_amount'] = o['price']*o['amount']
				if o["order_type"] == "sell_limit":
					open_orders["sell_orders"].append(o)
				elif o["order_type"] == "buy_limit":
					open_orders["buy_orders"].append(o)
		return open_orders


if __name__ == "__main__":
	log_level = log.INFO

	root = log.getLogger()
	root.setLevel(log_level)

	handler = log.StreamHandler(sys.stdout)
	handler.setLevel(log_level)
	formatter = log.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
	handler.setFormatter(formatter)
	root.addHandler(handler)