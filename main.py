import asyncio, sys, yaml
import logging as log

from market_data_collector import MarketDataCollector
from orderbook_manager import OrderbookManager

async def main():
	# start daemons
	market_task = asyncio.create_task(MarketDataCollector().daemon())
	orderbook_task = asyncio.create_task(OrderbookManager().monitor())
	#while True:
	await asyncio.sleep(10)

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

	asyncio.run(main())
