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

        # Index our market information by market string
        markets = self.api.get("/v1/markets")['markets']
        # Set some convenience keys so we can pass around just the dict
        for m in markets:
            m['string'] = "{market_currency}_{base_currency}".format(**m)
        self.market_map = {m['string']: m for m in markets}

    def get_balances(self):
        b_data = self.api.get("/v1/user/balances_all")
        balances = {}
        for b in b_data['balances'] + b_data['order_balances']:
            balances.setdefault(b['currency'], 0)
            balances[b['currency']] += Decimal(b['balance'])
        return balances

    def compute_allocations(self):
        """ Given our allocation % targets and our current balances, figure out
        how much market and base currency we would _ideally_ be
        allocating to each market
        return {
            "DOGE_BTC": [1200, 0.0012],
        }
        """
        balances = self.get_balances()
        reserve_config = self.config['currency_reserves']
        allocs = {}
        for market_string, market_alloc in self.config['market_allocations'].items():
            market = self.market_map[market_string]

            def allocate_coin(coin):
                """ Factor in allocation precentage and reserve amount to
                determine how much (base|market)-currency we're going to
                allocate to orders on this particular market. """
                reserve = Decimal(reserve_config[coin])
                alloc_perc = market_alloc[coin]

                post_reserve = balances[coin] - reserve
                return post_reserve * alloc_perc

            market_amount = allocate_coin(market['market_currency'])
            base_amount = allocate_coin(market['base_currency'])

            # TODO: At some point COIN will need to be based off base currency
            # precision. Not needed until we have ETH base markets really
            # TODO: removing fees isn't really part of allocating the funds,
            # it's part of placing the orders. Move this logic downstream for
            # clarity
            base_fee = (base_amount * Decimal(market['taker_fee'])).quantize(COIN, rounding='ROUND_UP')
            base_amount -= base_fee
            allocs[market_string] = (market_amount, base_amount)
        return allocs

    def allocate_orders(self, market_alloc, base_alloc):
        """ Given some amount of base and market currency determine how we'll
        allocate orders. Returns a tuple of (slippage_ratio, currency_allocation)
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
            amount = (ratio * base_alloc).quantize(COIN)
            buy_allocs.append((slip, amount))
        for slip, ratio in self.config['intervals']['sell'].items():
            ratio = Decimal(ratio)
            amount = (market_alloc * Decimal(ratio)).quantize(COIN)
            sell_allocs.append((slip, amount))
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
        for slip, amount in orders['sell']:
            slip = Decimal(slip)
            price = (midpoint + (midpoint * slip)).quantize(COIN)
            priced_sell_orders.append((price, amount))
        for slip, amount in orders['buy']:
            slip = Decimal(slip)
            price = (midpoint - (midpoint * slip)).quantize(COIN)
            priced_buy_orders.append((price, amount))
        return {'buy': priced_buy_orders, 'sell': priced_sell_orders}

    def rebalance_orders(self, allocation_profile, orders, force=False):
        if self.check_for_rebalance(allocation_profile, orders) is False and force is False:
            return

        if self.config['dry_run_mode']:
            log.warning("You are in dry run mode! Orders will not be cancelled or placed!")
        else:
            self.cancel_all_orders(orders)

        for market_string, profile in allocation_profile.items():
            market = self.market_map[market_string]
            for price, base_amount in profile['buy']:
                buy_amount = (base_amount / price).quantize(COIN)
                self.order('buy_limit', buy_amount, price, market)
            for price, amount in profile['sell']:
                self.order('sell_limit', amount, price, market)

    def order(self, order_type, amount, price, market):
        log.info("Place {:>10} on {string} {:>15} {market_currency} for {:>15.8f} {base_currency} each"
                 .format(order_type, amount, price, **market))
        if self.config['dry_run_mode'] is False:
            self.api.post('/v1/user/{}'.format(order_type),
                          amount=str(amount),
                          price=str(price),
                          market_id=market['id'])

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
        # Sleep to allow data scrapers to populate
        await asyncio.sleep(2)

        log.info("Starting orderbook manager; interval period %s sec", self.config['monitor_period'])
        while True:
            allocs = self.compute_allocations()
            allocation_profile = {}
            for market, a in allocs.items():
                midpoint = ExchangeDatastore.midpoints['qtrade'][market]
                allocation_profile[market] = self.price_orders(self.allocate_orders(a[0], a[1]), midpoint)
            self.rebalance_orders(allocation_profile, self.get_orders())
            await asyncio.sleep(self.config['monitor_period'])
