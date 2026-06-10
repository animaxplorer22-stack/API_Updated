# API_Updated
An api updated code that have fixed all flaws, like adding @limiter.limit() at every endpoint and last time, the duino server has only one pool that holds all the info like transaction history, balance and miner stats, which can cause RAM usage or a Crash, so i split it into 3 pools of info:

1.db_pool: reads user balances
2.tx_pool: reads transactions
3.miners_pool: reads mining stats

If the pools are split up instead of one pool, it would stabilise the API and make it FASTER and more effecient i hope 🙏

