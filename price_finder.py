import threading, sys, requests, json, time
import logging as log
from decimal import Decimal


class APIScraper:
	def __init__(self, url):
		self.url = url
		self.bid = None
		self.last = None
		self.ask = None
		self.midpoint = None

	def scrape_values(self): # dummy function, meant to be overridden
		pass


class BittrexScraper(APIScraper):
	def __init__(self):
		super().__init__("https://api.bittrex.com/api/v1.1/public/getticker?market=BTC-DOGE")

	def scrape_values(self):
		page = requests.get(self.url)

		if page.status_code == 200:
			log.debug("Content from %s was acquired successfully", self.url)
			content = json.loads(page.content)
			log.debug("Page content from %s is %s", self.url, content)
			self.bid = Decimal(content["result"]["Bid"])
			log.debug("Bid price is %s", self.bid)
			self.last = Decimal(content["result"]["Last"])
			log.debug("Last price is %s", self.last)
			self.ask = Decimal(content["result"]["Ask"])
			log.debug("Ask price is %s", self.ask)
			self.midpoint = (self.bid + self.last)/2
			log.info("Midpoint price from %s is %s", self.url, self.midpoint)
		else:
			log.warning("Content from %s could not be acquired, error code %s", self.url, page.status_code)
			return False

		return True


class qTradeScraper(APIScraper):
	def __init__(self):
		super().__init__("https://api.qtrade.io/v1/ticker/DOGE_BTC")

	def scrape_values(self):
		page = requests.get(self.url)

		if page.status_code == 200:
			log.debug("Content from %s was acquired successfully", self.url)
			content = json.loads(page.content)
			log.debug("Page content from %s is %s", self.url, content)
			self.bid = Decimal(content["data"]["bid"])
			log.debug("Bid price is %s", self.bid)
			self.last = Decimal(content["data"]["last"])
			log.debug("Last price is %s", self.last)
			self.ask = Decimal(content["data"]["ask"])
			log.debug("Ask price is %s", self.ask)
			self.midpoint = (self.bid + self.last)/2
			log.info("Midpoint price from %s is %s", self.url, self.midpoint)
		else:
			log.warning("Content from %s could not be acquired, error code %s", self.url, page.status_code)
			return False

		return True


class PriceFinder:
	def __init__(self, scrapers = [BittrexScraper(), qTradeScraper()]):
		self.scrapers = scrapers
		self._lock = threading.Lock()
		self.avg_midpoint = None
		self.update_interval = 2
		self.update_midpoint()

	def update_midpoint(self):
		log.info("Updating midpoint...")
		with self._lock:
			log.debug("PriceFinder locked to find new average midpoint")
			midpoint_count = 0
			midpoint_sum = Decimal(0)

			for s in self.scrapers:
				if s.scrape_values():
					midpoint_count += 1
					midpoint_sum += s.midpoint

			if midpoint_count == 0:
				log.warning("No midpoints were acquired!  Can't update average midpoint!")
			self.avg_midpoint = midpoint_sum/midpoint_count
			log.info("Average midpoint for %s sites is %s", midpoint_count, self.avg_midpoint)

			log.debug("Unlocking PriceFinder")

	def update_daemon(self):
		while True:
			self.update_midpoint()
			time.sleep(self.update_interval)


if __name__ == "__main__":
	log_level = log.INFO

	root = log.getLogger()
	root.setLevel(log_level)

	handler = log.StreamHandler(sys.stdout)
	handler.setLevel(log_level)
	formatter = log.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
	handler.setFormatter(formatter)
	root.addHandler(handler)

	pf = PriceFinder([BittrexScraper(), qTradeScraper()])
	pf.update_midpoint()