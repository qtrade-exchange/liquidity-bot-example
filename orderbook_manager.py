import asyncio
import logging
import time
from decimal import Decimal

from data_classes import ExchangeDatastore, PrivateDatastore
from market_scrapers import QTradeScraper
from qtrade_client.api import QtradeAPI

COIN = Decimal('.00000001')

log = logging.getLogger('mdc')


class OrderbookManager:
    def __init__(self, endpoint, key, config):
        self.config = config
        self.api = QtradeAPI(endpoint, key=key)
        self.orders = {'buy': buy_orders, 'sell': sell_orders}
        self.market_map = {"{market_currency}_{base_currency}".format(**m): m
                            for m in self.api.get("/v1/markets")['markets']}

    def compute_allocations(self):
        """ Given our allocation % targets and our current balances, figure out
        how much market and base currency we would _ideally_ be
        allocating to each market
        return {
            "DOGE_BTC": [1200, 0.0012],
        }
        """
        b_data = self.api.get("/v1/user/balances_all")
        balances = {}
        for b in b_data['balances'] + b_data['order_balances']:
            balances[b['currency']] = balances.setdefault(b['currency'], 0) + Decimal(b['balance'])

        allocs = {}
        alloc_conf = self.config['market_allocations']
        for market in alloc_conf:
            market_coin, base_coin = market.split('_')
            market_reserve = Decimal(self.config['currency_reserves'][market_coin])
            base_reserve = Decimal(self.config['currency_reserves'][base_coin])
            market_amount = (balances[market_coin]-market_reserve)*alloc_conf[market][market_coin]
            base_amount = (balances[base_coin]-base_reserve)*alloc_conf[market][base_coin]
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
            priced_sell_orders.append((midpoint+(midpoint*slip), ratio))
        for slip, ratio in orders['buy']:
            slip = Decimal(slip)
            priced_buy_orders.append((midpoint-(midpoint*slip), ratio))
        return {'buy': priced_buy_orders, 'sell': priced_sell_orders}

    def rebalance_orders(self, allocation_profile):
        for market, profile in allocation_profile.items():
            pass

    def old_rebalance_orders(self):
        self.cancel_all_orders()
        log.info("Placing new orders...")
        alloc = self.config['allocations']
        base_coin = "BTC"
        balances = self.api.balances()
        for coin in alloc:
            # if balances[coin] < alloc[coin]['reserve']:
            #     log.warning("%s balance is below reserve...", coin)
            #     continue
            if coin == base_coin:
                # set buy orders using BTC
                allocation_sum = 0
                num_markets = 0
                # sum all market coin allocations
                for market_coin in alloc[coin]:
                    if market_coin not in {'reserve', 'target'}:
                        allocation_sum += alloc[coin][market_coin]
                        num_markets += 1
                amount_to_allocate = min(min(alloc[coin]['target'], allocation_sum), PrivateDatastore.balances[coin] - Decimal(alloc[coin]['reserve']))
                # evenly distribute amount_to_allocate among all allocated coins and place orders
                for market_coin in alloc[coin]:
                    if market_coin not in {'reserve', 'target'}:
                        market_name = market_coin + "_" + coin
                        for i in self.config['intervals']['buy']:
                            price = ExchangeDatastore.midpoints['qtrade'][market_name]
                            price = price - Decimal(i) * price
                            buy_amount = amount_to_allocate / num_markets * Decimal(self.config['intervals']['buy'][i]) / price
                            log.info("Buying %s %s for %s %s each", buy_amount.quantize(COIN), market_coin, price.quantize(COIN), coin)
                            req = {'amount': str(buy_amount.quantize(COIN)),
                                   'price': str(price.quantize(COIN)),
                                   'market_id': PrivateDatastore.qtrade_market_map[market_name]['id']}
                            self.api.post('/v1/user/buy_limit', json=req)
            else:
                # set sell orders using other coins
                market_name = coin + "_" + base_coin
                amount_to_allocate = min(min(alloc[coin][base_coin], alloc[coin]['target']), PrivateDatastore.balances[coin]-Decimal(alloc[coin]['reserve']))
                for i in self.config['intervals']['sell']:
                    price = ExchangeDatastore.midpoints['qtrade'][market_name]
                    price = price - Decimal(i) * price
                    amount = amount_to_allocate * Decimal(self.config['intervals']['sell'][i])
                    req = {'amount': str(amount.quantize(COIN)),
                           'price': str(price.quantize(COIN)),
                           'market_id': PrivateDatastore.qtrade_market_map[market_name]['id']}
                    self.api.post('/v1/user/sell_limit', json=req)

    def cancel_all_orders(self):
        log.info("Cancelling all orders...")
        for bo in PrivateDatastore.buy_orders['qtrade']:
            log.debug("Cancelling order %s", bo['id'])
            PrivateDatastore.balances[bo['base_currency']] += bo['base_amount']
            self.api.post("https://api.qtrade.io/v1/user/cancel_order", json={"id":bo['id']})
        for so in PrivateDatastore.sell_orders['qtrade']:
            log.debug("Cancelling order %s", so['id'])
            PrivateDatastore.balances[so['market_currency']] += so['amount']
            self.api.post("https://api.qtrade.io/v1/user/cancel_order", json={"id":so['id']})

    # this function duplicates some behavior in check_placed_orders, plan to remove
    def check_coin_allocations(self, coin):
        current_allocs = dict()
        for m in PrivateDatastore.buy_orders.values(): # for each market
            for bo in m: # for each buy order on that market
                if bo['base_currency'] == coin:
                    try:
                        current_allocs[bo['market_currency']] += bo['base_amount']
                    except KeyError:
                        current_allocs[bo['market_currency']] = bo['base_amount']
        for m in PrivateDatastore.sell_orders.values():
            for so in m:
                if so['market_currency'] == coin:
                    try:
                        current_allocs[so['base_currency']] += so['amount']
                    except KeyError:
                        current_allocs[so['base_currency']] = so['amount']
        log.info("%s current allocations: %s", coin, current_allocs)
        for m_coin in current_allocs:
            if current_allocs[m_coin] > self.config['allocations'][coin][m_coin]:
                return True # trigger a rebalance
        return False

    # plan to remove
    def check_coin_reserve(self, coin):
        bal = PrivateDatastore.balances[coin]
        res = Decimal(self.config['allocations'][coin]['reserve'])
        if (res - bal)/res > self.config['reserve_margin']:
            log.info("Not enough %s in reserve!", coin)
            return True # trigger a rebalance
        return False

    # plan to remove
    def check_placed_orders(self, coin):
        if coin == 'BTC':
            if not PrivateDatastore.buy_orders['qtrade']:
                log.info("There are currently no buy orders!")
                return True
            total_allocated = 0
            market_allocated = dict() # allocated BTC to buy each coin
            num_buy_orders = dict() # number of buy orders per coin
            for bo in PrivateDatastore.buy_orders['qtrade']:
                market_allocated[bo['market_currency']] = market_allocated.setdefault(bo['market_currency'], Decimal(0)) + bo['base_amount']
                total_allocated += bo['base_amount']
                num_buy_orders[bo['market_currency']] = num_buy_orders.setdefault(bo['market_currency'], Decimal(0)) + 1
            if total_allocated > self.config['allocations'][coin]['target']:
                log.info("Too much %s allocated to buy other coins!", coin)
                return True
            if {x for x in set(num_buy_orders.values()) if x != len(self.config['intervals']['buy'])}:
                log.info("Not enough buy orders currently on the market!")
                return True
            for market_coin in market_allocated:
                if market_allocated[market_coin] > self.config['allocations'][coin][market_coin]:
                    log.info("Too much %s allocated to buy %s!", coin, market_coin)
                    return True
        else:
            base_coin = 'BTC'
            if not PrivateDatastore.sell_orders['qtrade']:
                log.info("There are currently no sell orders!")
                return True
            total_allocated = 0
            num_sell_orders = 0
            for so in PrivateDatastore.sell_orders['qtrade']:
                if so['market_coin'] == coin:
                    total_allocated += so['amount']
                    num_sell_orders += 1
            if total_allocated > self.config['allocations'][base_coin]:
                log.info("Selling too much %s for %s!", coin, base_coin)
                return True
            if num_sell_orders != len(self.config['intervals']['buy']):
                log.info("Not enough %s sell orders currently on the market!", coin)
                return True
        return False

    def update_orders(self):
        orders = self.api.get("/v1/user/orders")["orders"]

        log.debug("Updating orders...")
        buy_orders = []
        sell_orders = []
        for o in orders:
            if o['open']:
                mi = self.api.get("/v1/market/" + str(o['market_id']))['market']
                o['price'] = Decimal(o['price'])
                o['market_amount_remaining'] = Decimal(o['market_amount_remaining'])
                o['base_amount'] = o['price'] * o['market_amount_remaining']
                o['market'] = mi['market_currency'] + '_' + mi['base_currency']
                if o["order_type"] == "sell_limit":
                    sell_orders.append(o)
                elif o["order_type"] == "buy_limit":
                    buy_orders.append(o)
        log.debug("Active buy orders: %s", buy_orders)
        log.debug("Active sell orders: %s", sell_orders)

        log.info("%s active buy orders", len(buy_orders))
        log.info("%s active sell orders", len(sell_orders))
        return {'buy': buy_orders, 'sell': sell_orders}

    def buy_sell_bias(self):
        return (.5, .5)

    async def monitor(self):
        while True:
            log.info("Monitoring market data...")
            allocs = self.compute_allocations()
            allocation_profile = {}
            for market, a in allocs.items():
                midpoint = ExchangeDatastore.midpoints[market]
                allocation_profile[market] = self.price_orders(self.allocate_orders(a[0], a[1]), midpoint)
            self.orders = self.update_orders()
            self.rebalance_orders(allocation_profile)
            await asyncio.sleep(self.config['monitor_period'])
