# Hermes Render paper-bot replacement

The root Dockerfile now runs the paperbot/ application from daytrader.gpt commit 0faf7ed.
The previous Hermes source is retained for rollback but is not copied into the image.
No legacy engine, AI agent, or live broker endpoint is launched.

Render service: srv-daifhnbm8hqs73clck3g (Free)
URL: https://hermestradingsystem.onrender.com

Paper-only hard limits: $5,000 capital and $100 planned risk per trade.
Broker-side stop/target brackets; one strategy entry per session.
Render Free can sleep or restart; continuous operation and timed exits are not guaranteed.
See paperbot/RENDER-FREE.md for strategy, recovery and operating limitations.

Start with PAPER_ENTRIES_ENABLED=false. Enable only after the other cloud runner
is disabled, no unowned broker exposure exists, and startup reconciliation passes.
The laptop task must remain disabled. Never run two independent trading hosts.
