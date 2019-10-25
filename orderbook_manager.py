import asyncio
import logging
import time
from decimal import Decimal

from data_classes import ExchangeDatastore, PrivateDatastore
from market_scrapers import QTradeScraper
from qtrade_client.api import QtradeAPI

COIN = Decimal('.00000001')
PERC = Decimal('.01')

log = logging.getLogger('obm')


class OrderbookManager:
    def __init__(self, endpoint, key, config):
        self.config = config
        self.api = QtradeAPI(endpoint, key=key)
        self.market_map = {"{market_currency}_{base_currency}".format(**m): m
                            for m in self.api.get("/v1/markets")['markets']}
        self.balances = {}

    def update_balances(self):
        b_data = self.api.get("/v1/user/balances_all")
        self.balances = {}
        for b in b_data['balances'] + b_data['order_balances']:
            self.balances[b['currency']] = self.balances.setdefault(b['currency'], 0) + Decimal(b['balance'])

    def compute_allocations(self):
        """ Given our allocation % targets and our current balances, figure out
        how much market and base currency we would _ideally_ be
        allocating to each market
        return {
            "DOGE_BTC": [1200, 0.0012],
        }
        """
        self.update_balances()
        allocs = {}
        alloc_conf = self.config['market_allocations']
        for market in alloc_conf:
            market_coin, base_coin = market.split('_')
            market_reserve = Decimal(self.config['currency_reserves'][market_coin])
            base_reserve = Decimal(self.config['currency_reserves'][base_coin])
            market_amount = (self.balances[market_coin]-market_reserve)*alloc_conf[market][market_coin]
            base_amount = (self.balances[base_coin]-base_reserve)*alloc_conf[market][base_coin]
            base_fee = (base_amount * Decimal(self.market_map[market]['taker_fee'])).quantize(COIN, rounding='ROUND_UP')
            base_amount -= base_fee
            allocs[market] = (market_amount, base_amount)
        return allocs

    def allocate_orders(self, market_alloc, base_alloc):
        """ Given some amount of base and market currency determine how we'll allocate orders 
        return {
            "buy": [
                (0.01, 0.00001256),
            ],
            "sell": [
                (0.01, 1250),
            ]
        }
        """
        buy_allocs = []
        sell_allocs = []
        for slip, ratio in self.config['intervals']['buy'].items():
            ratio = Decimal(ratio)
            buy_allocs.append((slip, ratio*base_alloc))
        for slip, ratio in self.config['intervals']['sell'].items():
            ratio = Decimal(ratio)
            sell_allocs.append((slip, market_alloc*ratio))
        return {'buy': buy_allocs, 'sell': sell_allocs}

    def price_orders(self, orders, midpoint):
        """
        return {
            "buy": [
                (0.00000033, 0.00001256),
            ],
            "sell": [
                (0.00000034, 1250),
            ]
        } """
        midpoint = Decimal(midpoint)
        priced_sell_orders = []
        priced_buy_orders = []
        for slip, ratio in orders['sell']:
            slip = Decimal(slip)
            priced_sell_orders.append((midpoint+(midpoint*slip).quantize(COIN), ratio))
        for slip, ratio in orders['buy']:
            slip = Decimal(slip)
            priced_buy_orders.append((midpoint-(midpoint*slip).quantize(COIN), ratio))
        return {'buy': priced_buy_orders, 'sell': priced_sell_orders}

    def rebalance_orders(self, allocation_profile, orders, force = False):
        if self.config['dry_run_mode']:
            log.warning("You are in dry run mode!  Orders will not be cancelled or placed!")
        if self.check_for_rebalance(allocation_profile, orders) or force:
            if not self.config['dry_run_mode']:
                self.cancel_all_orders(orders)
            for market, profile in allocation_profile.items():
                market_coin, base_coin = market.split('_')
                for price, amount in profile['buy']:
                    log.info("Placing an order to buy %s %s for %s %s each", (amount/price).quantize(COIN), market_coin, price.quantize(COIN), base_coin)
                    req = {'amount': str((amount/price).quantize(COIN)),
                           'price': str(price.quantize(COIN)),
                           'market_id': self.market_map[market]['id']}
                    if not self.config['dry_run_mode']:
                        self.api.post('/v1/user/buy_limit', json=req)
                for price, amount in profile['sell']:
                    log.info("Placing an order to sell %s %s for %s %s each", amount.quantize(COIN), market_coin, price.quantize(COIN), base_coin)
                    req = {'amount': str(amount.quantize(COIN)),
                           'price': str(price.quantize(COIN)),
                           'market_id': self.market_map[market]['id']}
                    if not self.config['dry_run_mode']:
                        self.api.post('/v1/user/sell_limit', json=req)

    def check_for_rebalance(self, allocation_profile, orders):
        for market, profile in allocation_profile.items():
            for price, amount in profile['buy']:
                try:
                    price_diff = min([abs(price - o['price']) / price for o in orders[market]['buy']])
                except(ValueError, KeyError):
                    log.info("Rebalance! No %s buy orders are placed!", market)
                    return True
                if price_diff >= self.config['price_tolerance']:
                    log.info("Rebalance! %s%% difference in %s buy order price", str((price_diff*100).quantize(PERC)), market)
                    return True
                try:
                    amount_diff = min([abs(amount - o['market_amount_remaining']*o['price']) / amount for o in orders[market]['buy']])
                except(ValueError, KeyError):
                    log.info("Rebalance! No %s buy orders are placed!", market)
                    return True
                if amount_diff >= self.config['amount_tolerance']:
                    log.info("Rebalance! %s%% difference in %s buy order amount", str((amount_diff*100).quantize(PERC)), market)
                    return True

            for price, amount in profile['sell']:
                try:
                    price_diff = min([abs(price - o['price']) / price for o in orders[market]['sell']])
                except(ValueError, KeyError):
                    log.info("Rebalance! No %s sell orders are placed!", market)
                    return True
                if price_diff >= self.config['price_tolerance']:
                    log.info("Rebalance! %s%% difference in %s sell order price", str((price_diff*100).quantize(PERC)), market)
                    return True
                try:
                    amount_diff = min([abs(amount - o['market_amount_remaining']) / amount for o in orders[market]['sell']])
                except(ValueError, KeyError):
                    log.info("Rebalance! No %s sell orders are placed!", market)
                    return True
                if amount_diff >= self.config['amount_tolerance']:
                    log.info("Rebalance! %s%% difference in %s sell order amount", str((amount_diff*100).quantize(PERC)), market)
                    return True

        for coin, bal in self.api.balances().items():
            bal = Decimal(bal)
            reserve_diff = (Decimal(self.config['currency_reserves'][coin]) - bal) / bal
            if reserve_diff >= self.config['reserve_tolerance']:
                log.info("Rebalance! %s%% difference in %s reserve", str((reserve_diff*100).quantize(PERC)), coin)
                return True

    def cancel_all_orders(self, orders):
        log.info("Cancelling all orders...")
        for market, m_ords in orders.items():
            for bo in m_ords['buy']:
                log.debug("Cancelling order %s", bo['id'])
                self.api.post("https://api.qtrade.io/v1/user/cancel_order", json={"id":bo['id']})
            for so in m_ords['sell']:
                log.debug("Cancelling order %s", so['id'])
                self.api.post("https://api.qtrade.io/v1/user/cancel_order", json={"id":so['id']})

    def get_orders(self):
        orders = self.api.get("/v1/user/orders")["orders"]

        log.debug("Updating orders...")
        sorted_orders = {}
        for o in orders:
            if o['open']:
                mi = self.api.get("/v1/market/" + str(o['market_id']))['market']
                o['price'] = Decimal(o['price'])
                o['market_amount_remaining'] = Decimal(o['market_amount_remaining'])
                o['base_amount'] = o['price'] * o['market_amount_remaining']
                market = mi['market_currency'] + '_' + mi['base_currency']
                sorted_orders.setdefault(market, {'buy': [], 'sell': []})
                if o["order_type"] == "sell_limit":
                    sorted_orders[market]['sell'].append(o)
                elif o["order_type"] == "buy_limit":
                    sorted_orders[market]['buy'].append(o)
        log.debug("Active buy orders: %s", sorted_orders)

        log.info("%s active buy orders", sum([len(market['buy']) for market in sorted_orders.values()]))
        log.info("%s active sell orders", sum([len(market['sell']) for market in sorted_orders.values()]))
        return sorted_orders

    def buy_sell_bias(self):
        return (.5, .5)

    def rebalance_orders_test(self):
        allocs = self.compute_allocations()
        allocation_profile = {}
        for market, a in allocs.items():
            midpoint = ExchangeDatastore.midpoints['qtrade'][market]
            allocation_profile[market] = self.price_orders(self.allocate_orders(a[0], a[1]), midpoint)
        return self.rebalance_orders(allocation_profile, self.get_orders())

    def check_for_rebalance_test(self):
        allocs = self.compute_allocations()
        allocation_profile = {}
        for market, a in allocs.items():
            midpoint = ExchangeDatastore.midpoints['qtrade'][market]
            allocation_profile[market] = self.price_orders(self.allocate_orders(a[0], a[1]), midpoint)
        return self.check_for_rebalance(allocation_profile, self.get_orders())

    async def monitor(self):
        await asyncio.sleep(self.config['monitor_period']*2)
        while True:
            log.info("Monitoring market data...")
            allocs = self.compute_allocations()
            allocation_profile = {}
            for market, a in allocs.items():
                midpoint = ExchangeDatastore.midpoints['qtrade'][market]
                allocation_profile[market] = self.price_orders(self.allocate_orders(a[0], a[1]), midpoint)
            self.rebalance_orders(allocation_profile, self.get_orders())
            await asyncio.sleep(self.config['monitor_period'])
