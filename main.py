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
    formatter = log.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root.addHandler(handler)

    hmac_key = keyfile.read().strip()
    config = yaml.load(config)

    ctx.obj['obm'] = OrderbookManager(endpoint, hmac_key, config['orderbook_manager'])
    ctx.obj['mdc'] = MarketDataCollector(config['market_data_collector'])


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


if __name__ == "__main__":
    cli(obj={})
