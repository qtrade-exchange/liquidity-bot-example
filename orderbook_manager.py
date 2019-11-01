import asyncio
import logging
import time
from decimal import Decimal

from data_classes import ExchangeDatastore, PrivateDatastore
from market_scrapers import QTradeScraper
from qtrade_client.api import QtradeAPI, APIException

from pprint import pprint

COIN = Decimal('.00000001')
PERC = Decimal('.01')

log = logging.getLogger('obm')


class OrderbookManager:

    def __init__(self, endpoint, key, config):
        self.config = config
        self.api = QtradeAPI(endpoint, key=key)
        self.prev_alloc_profile = None

    def compute_allocations(self):
        """ Given our allocation % targets and our current balances, figure out
        how much market and base currency we would _ideally_ be
        allocating to each market
        return {
            "DOGE_BTC": [1200, 0.0012],
        }
        """
        balances = {c: Decimal(b)
                    for c, b in self.api.balances_merged().items()}
        balances.update({c: 0 for c in self.config[
                        'currency_reserves'] if c not in balances.keys()})
        reserve_config = self.config['currency_reserves']
        allocs = {}
        for market_string, market_alloc in self.config['market_allocations'].items():
            market = self.api.markets[market_string]

            def allocate_coin(coin):
                """ Factor in allocation precentage and reserve amount to
                determine how much (base|market)-currency we're going to
                allocate to orders on this particular market. """
                reserve = Decimal(reserve_config[coin])
                alloc_perc = Decimal(market_alloc[coin])

                post_reserve = balances[coin] - reserve
                return max(post_reserve * alloc_perc, 0)

            market_amount = allocate_coin(market['market_currency']['code'])
            base_amount = allocate_coin(market['base_currency']['code'])

            # TODO: At some point COIN will need to be based off base currency
            # precision. Not needed until we have ETH base markets really
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
        for slip, ratio in self.config['intervals']['buy_limit'].items():
            ratio = Decimal(ratio)
            amount = (ratio * base_alloc).quantize(COIN)
            buy_allocs.append((slip, amount))
        for slip, ratio in self.config['intervals']['sell_limit'].items():
            ratio = Decimal(ratio)
            amount = (market_alloc * ratio).quantize(COIN)
            sell_allocs.append((slip, amount))
        return {'buy_limit': buy_allocs, 'sell_limit': sell_allocs}

    def price_orders(self, orders, bid, ask):
        """
        return {
            "buy": [
                (0.00000033, 0.00001256),
            ],
            "sell": [
                (0.00000034, 1250),
            ]
        } """
        priced_sell_orders = []
        priced_buy_orders = []
        for slip, amount in orders['sell_limit']:
            slip = Decimal(slip)
            price = (ask + (ask * slip)).quantize(COIN)
            priced_sell_orders.append((price, amount))
        for slip, amount in orders['buy_limit']:
            slip = Decimal(slip)
            price = (bid - (bid * slip)).quantize(COIN)
            priced_buy_orders.append((price, amount))
        return {'buy_limit': priced_buy_orders, 'sell_limit': priced_sell_orders}

    def rebalance_orders(self, allocation_profile, orders, force=False):
        if self.check_for_rebalance(allocation_profile) is False and force is False:
            return

        if self.config['dry_run_mode']:
            log.warning(
                "You are in dry run mode! Orders will not be cancelled or placed!")
            pprint(allocation_profile)
            return

        self.api.cancel_all_orders()

        # TODO: refactor this code to be less repetetive
        for market_string, profile in allocation_profile.items():
            for price, value in profile['buy_limit']:
                if value <= 0:
                    continue
                self.api.order('buy_limit', price, value=value,
                               market_string=market_string, prevent_taker=True)
                logging.info("Placing buy_limit on %s market for %s at %s",
                             market_string, value, price)
            for price, amount in profile['sell_limit']:
                if amount <= 0:
                    continue
                self.api.order('sell_limit', price, amount=amount,
                               market_string=market_string, prevent_taker=True)
                logging.info("Placing sell_limit on %s market for %s at %s",
                             market_string, amount, price)
        self.prev_alloc_profile = allocation_profile

    def check_for_rebalance(self, allocation_profile):
        if self.prev_alloc_profile is None:
            log.info("Rebalance! No previous rebalance data!")
            return True

        for market, profile in allocation_profile.items():
            prev_profile = self.prev_alloc_profile[market]
            for t in ('buy_limit', 'sell_limit'):
                for n, o in zip(profile[t], prev_profile[t]):
                    price_diff = (n[0] - o[0]) / n[0]
                    price_tol = self.config['price_tolerance']
                    if price_diff > price_tol:
                        if o[0] > price_diff:
                            log.info('Rebalance! %s %s price is %s%% higher than allotted',
                                     market, t, price_diff.quantize(PERC))
                        else:
                            log.info('Rebalance! %s %s price is %s%% lower than allotted',
                                     market, t, price_diff.quantize(PERC))
                        return True
                    if n[1] == 0:
                        continue
                    amount_diff = (n[1] - o[1]) / n[1]
                    amount_tol = self.config['amount_tolerance']
                    if amount_diff > amount_tol:
                        if o[1] > amount_diff:
                            log.info('Rebalance! %s %s amount is %s%% higher than allotted',
                                     market, t, amount_diff.quantize(PERC))
                        else:
                            log.info('Rebalance! %s %s amount is %s%% lower than allotted',
                                     market, t, amount_diff.quantize(PERC))
                        return True

        for coin, bal in self.api.balances().items():
            bal = Decimal(bal)
            res = self.config['currency_reserves'][coin]
            reserve_diff = abs(Decimal(res) - bal) / bal
            if reserve_diff >= self.config['reserve_tolerance']:
                if res > bal:
                    log.info("Rebalance! %s balance is %s%% lower than reserve",
                             coin, str((reserve_diff * 100).quantize(PERC)))
                else:
                    log.info("Rebalance! %s balance is %s%% higher than reserve",
                             coin, str((reserve_diff * 100).quantize(PERC)))
                return True
        return False

    def check_for_rebalance_old(self, allocation_profile, orders):
        """ Pull active orders from the API and ensure every order
        in the profile has a market counterpart within the thresholds """
        for market, profile in allocation_profile.items():
            for price, amount in profile['buy']:
                if amount == 0:
                    continue
                try:
                    price_diff = min(
                        [abs(price - o['price']) / price for o in orders[market]['buy']])
                except(ValueError, KeyError):
                    log.info("Rebalance! No %s buy orders are placed!", market)
                    return True
                if price_diff >= self.config['price_tolerance']:
                    log.info("Rebalance! %s%% difference in %s buy order price", str(
                        (price_diff * 100).quantize(PERC)), market)
                    return True
                try:
                    amount_diff = min([abs(amount - o['market_amount_remaining']
                                           * o['price']) / amount for o in orders[market]['buy']])
                except(ValueError, KeyError):
                    log.info("Rebalance! No %s buy orders are placed!", market)
                    return True
                if amount_diff >= self.config['amount_tolerance']:
                    log.info("Rebalance! %s%% difference in %s buy order amount", str(
                        (amount_diff * 100).quantize(PERC)), market)
                    return True

            for price, amount in profile['sell']:
                if amount == 0:
                    continue
                try:
                    price_diff = min(
                        [abs(price - o['price']) / price for o in orders[market]['sell']])
                except(ValueError, KeyError):
                    log.info("Rebalance! No %s sell orders are placed!", market)
                    return True
                if price_diff >= self.config['price_tolerance']:
                    log.info("Rebalance! %s%% difference in %s sell order price", str(
                        (price_diff * 100).quantize(PERC)), market)
                    return True
                try:
                    amount_diff = min(
                        [abs(amount - o['market_amount_remaining']) / amount for o in orders[market]['sell']])
                except(ValueError, KeyError):
                    log.info("Rebalance! No %s sell orders are placed!", market)
                    return True
                if amount_diff >= self.config['amount_tolerance']:
                    log.info("Rebalance! %s%% difference in %s sell order amount", str(
                        (amount_diff * 100).quantize(PERC)), market)
                    return True

        for coin, bal in self.api.balances().items():
            bal = Decimal(bal)
            reserve_diff = (
                Decimal(self.config['currency_reserves'][coin]) - bal) / bal
            if reserve_diff >= self.config['reserve_tolerance']:
                log.info("Rebalance! %s%% difference in %s reserve",
                         str((reserve_diff * 100).quantize(PERC)), coin)
                return True
        return False

    def get_orders(self):
        orders = self.api.get("/v1/user/orders")["orders"]

        log.debug("Updating orders...")
        sorted_orders = {}
        for o in orders:
            if o['open']:
                mi = self.api.get(
                    "/v1/market/" + str(o['market_id']))['market']
                o['price'] = Decimal(o['price'])
                o['market_amount_remaining'] = Decimal(
                    o['market_amount_remaining'])
                o['base_amount'] = o['price'] * o['market_amount_remaining']
                market = mi['market_currency'] + '_' + mi['base_currency']
                sorted_orders.setdefault(market, {'buy': [], 'sell': []})
                if o["order_type"] == "sell_limit":
                    sorted_orders[market]['sell'].append(o)
                elif o["order_type"] == "buy_limit":
                    sorted_orders[market]['buy'].append(o)
        log.debug("Active buy orders: %s", sorted_orders)

        log.info("%s active buy orders", sum(
            [len(market['buy']) for market in sorted_orders.values()]))
        log.info("%s active sell orders", sum(
            [len(market['sell']) for market in sorted_orders.values()]))
        return sorted_orders

    def generate_orders(self, force_rebalance=False):
        allocs = self.compute_allocations()
        allocation_profile = {}
        for market, a in allocs.items():
            if market == 'LTC_BTC':
                continue
            #bids = [m[market]['bid']
            #        for e, m in ExchangeDatastore.tickers.items()]
            #avg_bid = sum(bids) / len(bids)
            #asks = [m[market]['ask']
            #        for e, m in ExchangeDatastore.tickers.items()]
            #avg_ask = sum(asks) / len(asks)
            bid = ExchangeDatastore.tickers['bittrex'][market]['bid']
            ask = ExchangeDatastore.tickers['bittrex'][market]['ask']
            log.info("Generating %s orders with bid %s and ask %s",
                     market, bid, ask)
            allocation_profile[market] = self.price_orders(
                self.allocate_orders(a[0], a[1]), bid, ask)
        self.rebalance_orders(allocation_profile,
                              self.get_orders(), force=force_rebalance)

    async def monitor(self):
        # Sleep to allow data scrapers to populate
        await asyncio.sleep(2)

        log.info("Starting orderbook manager; interval period %s sec",
                 self.config['monitor_period'])
        while True:
            try:
                self.generate_orders()
                await asyncio.sleep(self.config['monitor_period'])
            except Exception:
                log.warning("Orderbook manager loop exploded", exc_info=True)
