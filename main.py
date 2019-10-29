import asyncio
import yaml
import sys
import click
import logging as log

from market_data_collector import MarketDataCollector
from orderbook_manager import OrderbookManager


@click.group()
@click.option('--config', '-c', default="config.yml", type=click.File())
@click.option('--endpoint', '-e', default="https://api.qtrade.io", help='qtrade backend endpoint')
@click.option('--keyfile', '-f', default="lpbot_hmac.txt", help='a file with the hmac key', type=click.File('r'))
@click.option('--verbose', '-v', default=False)
@click.pass_context
def cli(ctx, config, endpoint, keyfile, verbose):
    log_level = "DEBUG" if verbose is True else "INFO"

    root = log.getLogger()
    root.setLevel(log_level)
    handler = log.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    formatter = log.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root.addHandler(handler)

    hmac_key = keyfile.read().strip()
    config = yaml.load(config)

    ctx.obj['mdc'] = MarketDataCollector(config['market_data_collector'])
    ctx.obj['obm'] = OrderbookManager(
        endpoint, hmac_key, config['orderbook_manager'])


@cli.command()
@click.pass_context
def run(ctx):
    loop = asyncio.get_event_loop()
    loop.create_task(ctx.obj['obm'].monitor())
    loop.create_task(ctx.obj['mdc'].daemon())
    loop.run_forever()


@cli.command()
@click.pass_context
def mdc(ctx):
    loop = asyncio.get_event_loop()
    loop.create_task(ctx.obj['mdc'].daemon())
    loop.run_forever()


@cli.command()
@click.pass_context
def obm(ctx):
    loop = asyncio.get_event_loop()
    loop.create_task(ctx.obj['obm'].monitor())
    loop.run_forever()


@cli.command()
@click.pass_context
def balances_test(ctx):
    ba = ctx.obj['obm'].api.get("/v1/user/balances_all")
    print(ba)


@cli.command()
@click.pass_context
def compute_allocations_test(ctx):
    print(ctx.obj['obm'].compute_allocations())


@cli.command()
@click.pass_context
def allocate_orders_test(ctx):
    allocs = ctx.obj['obm'].compute_allocations()
    a = allocs.popitem()[1]
    print(ctx.obj['obm'].allocate_orders(a[1], a[0]))


@cli.command()
@click.pass_context
def price_orders_test(ctx):
    allocs = ctx.obj['obm'].compute_allocations()
    a = allocs.popitem()[1]
    print(ctx.obj['obm'].price_orders(
        ctx.obj['obm'].allocate_orders(a[0], a[1]), 0.0000033))


@cli.command()
@click.pass_context
def update_orders_test(ctx):
    print(ctx.obj['obm'].update_orders())


@cli.command()
@click.pass_context
def rebalance_orders_test(ctx):
    ctx.obj['mdc'].update_tickers()
    ctx.obj['mdc'].update_midpoints()
    print(ctx.obj['obm'].rebalance_orders_test())


@cli.command()
@click.pass_context
def check_for_rebalance_test(ctx):
    ctx.obj['mdc'].update_tickers()
    ctx.obj['mdc'].update_midpoints()
    print(ctx.obj['obm'].check_for_rebalance_test())


if __name__ == "__main__":
    cli(obj={})
