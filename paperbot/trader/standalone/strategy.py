"""One deterministic opening-range breakout paper trade per US session."""
import datetime as dt
from decimal import Decimal as D, ROUND_FLOOR, ROUND_CEILING
import json
import os
from zoneinfo import ZoneInfo
import urllib.parse

# Imported under script execution and by offline tests.
from runner import entries_enabled, instant, save, validate

NY = ZoneInfo('America/New_York')
WATCHLIST = ('AAPL','MSFT','NVDA','AMZN','GOOGL','META','SPY')


def candidate(symbol, bars, snap, start, now):
    bars = sorted([b for b in bars if start <= instant(b['t']) and
                   instant(b['t'])+dt.timedelta(minutes=5) <= now], key=lambda b:b['t'])
    if len(bars) < 4:
        return None
    # Require complete opening range and contiguous latest two 5-minute bars.
    if any(instant(bars[i]['t']) != start+dt.timedelta(minutes=5*i) for i in range(3)):
        return None
    last, prev = bars[-1], bars[-2]
    if not 0 <= (now-instant(last['t'])-dt.timedelta(minutes=5)).total_seconds() <= 90:
        return None
    if instant(last['t'])-instant(prev['t']) != dt.timedelta(minutes=5):
        return None
    high, low = max(D(str(b['h'])) for b in bars[:3]), min(D(str(b['l'])) for b in bars[:3])
    if not D(str(prev['c'])) <= high < D(str(last['c'])):
        return None
    total_volume = sum(D(str(b['v'])) for b in bars)
    if total_volume <= 0 or D(str(last['v'])) < sum(D(str(b['v'])) for b in bars[-4:-1])/D(3)*D('1.2'):
        return None
    vwap = sum(D(str(b.get('vw',b['c'])))*D(str(b['v'])) for b in bars)/total_volume
    if D(str(last['c'])) <= vwap:
        return None
    quote, trade = snap.get('latestQuote'), snap.get('latestTrade')
    if not quote or not trade or any(not 0 <= (now-instant(x['t'])).total_seconds() <= 60 for x in (quote,trade)):
        return None
    ask, bid = D(str(quote['ap'])), D(str(quote['bp']))
    if not 0 < bid <= ask or (ask-bid)/ask > D('0.001'):
        return None
    entry = ask.quantize(D('.01'), rounding=ROUND_CEILING)
    stop = low.quantize(D('.01'), rounding=ROUND_FLOOR)-D('.01')
    risk = entry-stop
    if not D('.002') <= risk/entry <= D('.02') or not high < entry <= high+D('.25')*(high-low):
        return None
    if D(str(trade['p'])) <= high or D(str(trade['p'])) > entry+D('.05'):
        return None
    # Retain the existing 75% per-position cap and $10 planned-risk cushion.
    qty = int(min(D(3750)/entry, D(90)/risk))
    if qty < 1:
        return None
    target = (entry+2*risk).quantize(D('.01'))
    return dict(symbol=symbol,qty=qty,entry=str(entry),stop=str(stop),target=str(target),
                score=float(D(str(last['v']))/(sum(D(str(b['v'])) for b in bars[-4:-1])/3)),
                signal_bar=last['t'])


def select_next(broker, root, now):
    settings_path = root/'strategy.json'
    if not settings_path.exists():
        return None
    settings = json.loads(settings_path.read_text())
    if not entries_enabled() or settings.get('enabled') is not True or (root/'PAUSE_ENTRIES').exists():
        return 'idle: automatic entries paused'
    if settings.get('paper') is not True:
        raise ValueError('Strategy requires paper mode')
    clock = broker.call('/clock')
    if not clock['is_open']:
        return 'idle: market closed'
    day = now.astimezone(NY).date()
    day_file = root/('selection-'+day.isoformat()+'.json')
    if day_file.exists():
        selected = json.loads(day_file.read_text())
        current_path = root/'plan.json'
        current = json.loads(current_path.read_text()) if current_path.exists() else None
        if current is None or current['client_order_id'] != selected['client_order_id']:
            save(current_path,selected)
            return 'plan_selected'
        return 'idle: daily trade allowance used'
    calendar = broker.call('/calendar?start='+str(day)+'&end='+str(day))
    if len(calendar) != 1:
        return 'idle: no exchange session'
    start = dt.datetime.combine(day,dt.time.fromisoformat(calendar[0]['open']),NY)
    close = dt.datetime.combine(day,dt.time.fromisoformat(calendar[0]['close']),NY)
    # 19:55 UTC is 01:25 IST next day, regardless of US daylight saving time.
    ist_deadline = dt.datetime.combine(day,dt.time(19,55),dt.timezone.utc)
    deadline = min(close-dt.timedelta(minutes=5),ist_deadline)
    if not start+dt.timedelta(minutes=20) <= now < deadline-dt.timedelta(minutes=30):
        return 'idle: outside strategy entry window'
    if broker.call('/positions') or broker.call('/orders?status=open'):
        return 'attention: paper account occupied without active plan; reconcile before trading'
    # A fresh cloud disk must not forget a trade placed by the laptop today.
    after = dt.datetime.combine(day,dt.time(),NY).isoformat()
    history = broker.call('/orders?'+urllib.parse.urlencode(dict(status='all',after=after,limit=500,direction='desc')))
    if len(history) >= 500:
        return 'attention: session order history truncated; no new entry'
    if any(o.get('client_order_id','').startswith('auto-orb-'+day.strftime('%Y%m%d')) for o in history):
        return 'idle: broker records show daily trade allowance used'
    scan_path = root/'scan.json'
    if scan_path.exists() and (now-instant(json.loads(scan_path.read_text())['at'])).total_seconds()<60:
        return 'scanning'
    symbols = ','.join(WATCHLIST)
    query = urllib.parse.urlencode(dict(symbols=symbols,timeframe='5Min',start=start.isoformat(),
        end=now.isoformat(),feed='iex',adjustment='raw',limit=10000))
    data = broker.call('/stocks/bars?'+query,market_data=True)
    if data.get('next_page_token'):
        return 'attention: incomplete market data; no selection'
    snapshots = broker.call('/stocks/snapshots?'+urllib.parse.urlencode(dict(symbols=symbols,feed='iex')),market_data=True)
    choices = []
    for symbol in WATCHLIST:
        pick = candidate(symbol,(data.get('bars') or {}).get(symbol,[]),snapshots.get(symbol,{}),start,now)
        if pick:
            asset = broker.call('/assets/'+symbol)
            if asset and asset.get('tradable') and asset['status']=='active':
                choices.append(pick)
    save(scan_path,dict(at=now.isoformat(),candidates=choices,feed='iex'))
    if not choices:
        return 'scanning'
    best = max(choices,key=lambda x:(x['score'],x['symbol']))
    cid = 'auto-orb-'+day.strftime('%Y%m%d')
    if os.environ.get('TRADER_STORAGE') != 'broker':
        cid += '-'+best['symbol']
    plan = {k:best[k] for k in ('symbol','qty','entry','stop','target')}
    plan.update(paper=True,mode='armed',client_order_id=cid,exit_client_order_id=cid+'-exit',
        entry_after=now.isoformat(),cancel_at=(now+dt.timedelta(minutes=3)).isoformat(),
        flatten_at=(deadline-dt.timedelta(minutes=1)).isoformat(),deadline=deadline.isoformat(),
        authorization=settings['authorization'],strategy='15-minute opening range breakout; 2R target; IEX',
        signal_bar=best['signal_bar'])
    validate(plan)
    # Reserve the session before publishing a plan; crash recovery reloads it.
    save(day_file,plan)
    save(root/'plan.json',plan)
    return 'plan_selected'
