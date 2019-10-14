## Liquidity Provider Bot

Design objectives:

 - use built-in Python multithreading

THREAD 1:
 - get midpoint prices from various markets

THREAD 2:
 - read midpoints
 - place buy and sell orders at configurable intervals below and above midpoints

 Possible features:
  - Weight a market's midpoint value with volume