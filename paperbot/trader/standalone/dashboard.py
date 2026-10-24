"""Read-only, authenticated paper-trade dashboard data."""
import datetime as dt
import json
import threading
import time
from pathlib import Path
from runner import Broker

lock = threading.Lock()
cached = None
cached_at = 0


def owned(order):
    cid = order.get('client_order_id', '')
    return cid.startswith('auto-orb-') or cid.startswith('paper-msft-20261023-')


def ticket(order, role):
    keys = ('id','symbol','side','qty','filled_qty','filled_avg_price','status',
            'type','limit_price','stop_price','created_at','filled_at','updated_at')
    return dict({k: order.get(k) for k in keys}, role=role)


def snapshot(root, broker=None):
    global cached, cached_at
    with lock:
        if cached is not None and time.monotonic()-cached_at < 5:
            return cached
        broker = broker or Broker()
        clock = broker.call('/clock')
        orders = broker.call('/orders?status=all&nested=true&limit=100&direction=desc')
        parents = [o for o in orders if owned(o)]
        tickets = []
        for order in parents:
            tickets.append(ticket(order, 'Exit' if order.get('side') == 'sell' else 'Entry'))
            for leg in order.get('legs') or []:
                tickets.append(ticket(leg, 'Stop loss' if 'stop' in leg.get('type','') else 'Take profit'))
        tickets = list({t['id']:t for t in tickets}.values())
        symbols = {o['symbol'] for o in parents}
        positions = []
        for p in broker.call('/positions'):
            if p['symbol'] in symbols:
                positions.append({k:p.get(k) for k in ('symbol','qty','avg_entry_price',
                    'current_price','market_value','unrealized_pl','unrealized_plpc')})
        events = []
        for t in tickets:
            if float(t.get('filled_qty') or 0) > 0:
                events.append(dict(id=t['id']+'-fill',time=t['filled_at'] or t['updated_at'],
                    kind='buy' if t['side']=='buy' else 'sell',symbol=t['symbol'],
                    text=f"{t['side'].upper()} {t['filled_qty']} {t['symbol']} at ${t['filled_avg_price'] or 'pending'}",role=t['role']))
            else:
                events.append(dict(id=t['id']+'-'+str(t['status']),time=t['updated_at'] or t['created_at'],
                    kind='order',symbol=t['symbol'],text=f"{t['symbol']} · {t['role']} · {t['status']}",role=t['role']))
        status = {}
        try:
            status = json.loads((Path(root)/'status.json').read_text())
        except (OSError,ValueError):
            pass
        cached = dict(updated_at=dt.datetime.now(dt.timezone.utc).isoformat(),market=clock,
            runner={k:status.get(k) for k in ('status','updated_at','needs_attention')},
            positions=positions,orders=sorted(tickets,key=lambda t:t['created_at'] or '',reverse=True),
            events=sorted(events,key=lambda e:e['time'] or '',reverse=True)[:40],
            history_note='Latest 100 broker parent orders; only Daytrader strategy orders are shown.')
        cached_at = time.monotonic()
        return cached
