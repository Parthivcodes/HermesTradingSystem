"""Rebuild a missing plan from Alpaca; no broker writes during startup."""
import datetime as dt
from decimal import Decimal as D
import re
import urllib.parse
from zoneinfo import ZoneInfo
from runner import TERMINAL, instant, save, validate


def recover(broker, root, now):
    # Existing cache is never rewritten. The engine reconciles it before selection.
    if (root/'plan.json').exists():
        return
    after = (now-dt.timedelta(days=30)).isoformat()
    history = broker.call('/orders?'+urllib.parse.urlencode(dict(status='all',after=after,
        limit=500,direction='desc',nested='true')))
    if len(history) >= 500:
        raise RuntimeError('Recovery history truncated; manual reconciliation required')
    positions = broker.call('/positions')
    opened = broker.call('/orders?status=open&nested=true')
    candidates = []
    for order in history:
        cid=order.get('client_order_id','')
        if not re.fullmatch(r'auto-orb-\d{8}(?:-[A-Z]{1,5})?',cid):
            continue
        if order.get('side') != 'buy' or order.get('order_class') != 'bracket':
            raise RuntimeError('Unexpected strategy order; recovery stopped')
        order=broker.call('/orders/'+order['id']+'?nested=true')
        legs=order.get('legs') or []
        closing=broker.by_client(cid+'-exit')
        sold=sum((D(x['filled_qty']) for x in legs),D(0))
        if closing:sold+=D(closing['filled_qty'])
        outstanding=D(order['filled_qty'])-sold
        active=any(x['status'] not in TERMINAL for x in [order]+legs+([closing] if closing else []))
        if active or outstanding:
            candidates.append(order)
    if len(candidates)>1:
        raise RuntimeError('Multiple unfinished strategy orders; recovery stopped')
    if not candidates:
        if positions or opened:
            raise RuntimeError('Unowned position or order; no automatic entry permitted')
        return
    order=candidates[0]
    legs=order.get('legs') or []
    stop=next((x.get('stop_price') for x in legs if x.get('stop_price')),None)
    target=next((x.get('limit_price') for x in legs if x.get('type')=='limit'),None)
    if len(legs)!=2 or not stop or not target:
        raise RuntimeError('Incomplete bracket records; recovery stopped')
    symbol=order['symbol']
    if any(x['symbol']!=symbol for x in positions):
        raise RuntimeError('Unrelated positions present; recovery stopped')
    created=instant(order['created_at'])
    day=created.astimezone(ZoneInfo('America/New_York')).date()
    calendar=broker.call('/calendar?start='+str(day)+'&end='+str(day))
    if len(calendar)!=1:raise RuntimeError('Missing exchange session during recovery')
    close=dt.datetime.combine(day,dt.time.fromisoformat(calendar[0]['close']),ZoneInfo('America/New_York'))
    deadline=min(close-dt.timedelta(minutes=5),dt.datetime.combine(day,dt.time(19,55),dt.timezone.utc))
    plan=dict(paper=True,mode='monitor_only',symbol=symbol,qty=int(D(order['qty'])),
        entry=order['limit_price'],stop=stop,target=target,client_order_id=order['client_order_id'],
        exit_client_order_id=order['client_order_id']+'-exit',entry_after=created.isoformat(),
        cancel_at=(created+dt.timedelta(minutes=3)).isoformat(),
        flatten_at=(deadline-dt.timedelta(minutes=1)).isoformat(),deadline=deadline.isoformat(),
        authorization='Recover the user-authorized automatic paper strategy from broker records.')
    validate(plan)
    save(root/'plan.json',plan)
