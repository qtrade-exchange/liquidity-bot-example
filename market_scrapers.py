import threading, sys, json, time
import logging as log
from decimal import Decimal

from qtrade_client.api import QtradeAPI

class APIScraper:
	def __init__(self, market_name, api):
		self.market_name = market_name
		self.api = api

	def scrape_ticker(self): # dummy function, meant to be overridden
		pass

## DEPRECATED ##
#class BittrexScraper(APIScraper):
#	def __init__(self):
#		super().__init__("bittrex", "https://api.bittrex.com/api/v1.1/public/getticker?market=BTC-DOGE")
#
#	def scrape_ticker(self):
#		page = resuests.get(self.url)
#
#		if page.status_code == 200:
#			log.debug("Content from %s was acquired successfully", self.url)
#			content = json.loads(page.content)
#			log.debug("Page content from %s is %s", self.url, content)
#			bid = Decimal(content["result"]["Bid"])
#			log.debug("Bid price is %s", bid)
#			last = Decimal(content["result"]["Last"])
#			log.debug("Last price is %s", last)
#			ask = Decimal(content["result"]["Ask"])
#			log.debug("Ask price is %s", ask)
#			return {"bid":bid, "last":last, "ask":ask}
#		else:
#			log.warning("Content from %s could not be acquired, error code %s", self.url, page.status_code)


class qTradeScraper(APIScraper):
	def __init__(self):
		super().__init__("qtrade", QtradeAPI("https://api.qtrade.io", key=open("lpbot_hmac.txt", "r").read().strip()))

	def scrape_ticker(self):
		res = self.api.get("/v1/ticker/DOGE_BTC")

		log.debug("Ticker from %s was acquired successfully", self.market_name)
		bid = Decimal(res["bid"])
		log.debug("Bid price is %s", bid)
		last = Decimal(res["last"])
		log.debug("Last price is %s", last)
		ask = Decimal(res["ask"])
		log.debug("Ask price is %s", ask)
		return {"bid":bid, "last":last, "ask":ask}

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
				mi = self.get_market_info(o["market_id"])
				this_order = {'price': Decimal(o['price']),
							'amount': Decimal(o['market_amount_remaining']),
							"base_amount": Decimal(o['base_amount']),
							'market_currency': mi['market_currency'],
							'base_currency': mi['base_currency']}
				if o["order_type"] == "sell_limit":
					open_orders["sell_orders"].append(this_order)
				elif o["order_type"] == "buy_limit":
					open_orders["buy_orders"].append(this_order)
		return open_orders

	def get_market_info(self, market_id):
		markets = self.api.get("/v1/markets")["markets"]
		for m in markets:
			if m["id"] == market_id:
				return m


if __name__ == "__main__":
	log_level = log.INFO

	root = log.getLogger()
	root.setLevel(log_level)

	handler = log.StreamHandler(sys.stdout)
	handler.setLevel(log_level)
	formatter = log.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
	handler.setFormatter(formatter)
	root.addHandler(handler)