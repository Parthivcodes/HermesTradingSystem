# Alpaca paper trader on Render Free

Requested hosting: **Render Free only**. No paid worker, disk or database.
Uses a free Python web service, serving a minimal public status endpoint and
supervising the paper-trading runner. No public order controls, account
balances, order details, or credentials are exposed.

**Not an always-on service:** Render Free sleeps after 15 minutes without
incoming traffic and can restart or be suspended at quota limits. Background
API polling does not prevent sleep. Broker-held stop/target orders remain at
Alpaca, but new entries, unfilled-entry cancellation, and timed exits only run
while Render is awake. The 01:25 IST exit deadline cannot be guaranteed.
No self-pings or artificial traffic are installed to bypass free-plan limits.

Hard limits remain PAPER only, $5,000 capital and $100 planned risk per trade.
Automatic sizing uses at most $3,750 and $90 planned risk, with one entry per
US session. Stop slippage can exceed planned risk. The experimental breakout
strategy is not backtested or guaranteed profitable.

## Recovery without paid storage

Alpaca is the durable order ledger. On startup the runner reconstructs an
unfinished strategy bracket from the broker, including its protective prices
and exchange-session deadline, before allowing new selections. It refuses
unowned positions, missing bracket information or truncated history. Current
day history prevents another trade after a completed/canceled entry.

Free-host entry IDs use `auto-orb-YYYYMMDD`, independent of the chosen symbol,
and exits append `-exit`. Stable broker client IDs prevent a restart from
creating a second order for the same session. Local files are only a cache;
they are lost when Render restarts. Previously accepted strategy orders remain
discoverable at Alpaca. No durable record of an attempt that never reached
Alpaca can survive a complete cache loss.

## Service configuration

- Runtime Python 3.12, plan **free**, region Oregon, one instance.
- Build: `pip install -r requirements.txt` followed by offline tests with cloud
  runtime environment switches unset for test isolation.
- Start: `python -u trader/standalone/web.py`.
- Secrets: ALPACA_API_KEY, ALPACA_SECRET_KEY (paper credentials only).
- ALPACA_PAPER_TRADE=true, TRADER_CLOUD=true, TRADER_STORAGE=broker.
- TRADER_STATE_DIR=/tmp/paper-trader.
- PAPER_ENTRIES_ENABLED=false initially; true only after safe cutover.
- Auto-deploy off. No disk, database, cron job, paid plan, or paid add-on.

Verify healthy broker reconciliation in private Render logs. The public page
reports only whether the runner process is alive, not broker health. Pause
entries by setting PAPER_ENTRIES_ENABLED=false and deploying; exits continue
while the service is awake. Do not suspend a service with an open paper trade.

Before enabling cloud entries, verify the paper account is flat, pause and
disable the Windows task AlpacaPaperStandalone, stop its process, then recheck
the account. Do not run both hosts at once. Keep the local pause marker in place.

Free hours are shared across the Render workspace. Bandwidth/build usage may
have overage rules if a payment method is present; this deployment does not
upgrade plans or change billing settings for other services. Check the
workspace's free quotas and spending controls. Exceeding free availability
must not be resolved by enabling a paid service.

Sources: [Render free limits](https://render.com/docs/free),
[Alpaca order IDs and bracket orders](https://docs.alpaca.markets/us/docs/orders-at-alpaca).

Offline tests: `python -m unittest discover -s tests -p "test_*.py" -v`.
The alternative VM setup is retained in FREE-CLOUD.md for reference only.
