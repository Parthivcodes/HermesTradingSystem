"""Deterministic paper bracket executor. Python stdlib only; no AI API calls."""
import argparse
import ctypes
import datetime as dt
from decimal import Decimal as D
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import threading
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request

SOURCE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('TRADER_STATE_DIR', str(SOURCE))).resolve()
TERMINAL = {'filled', 'canceled', 'expired', 'rejected'}


def entries_enabled():
    return os.environ.get('PAPER_ENTRIES_ENABLED', 'true').lower() == 'true'


def credentials():
    keys = ('ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'ALPACA_PAPER_TRADE')
    if any(k in os.environ for k in keys):
        c = {k: os.environ.get(k, '') for k in keys}
    elif os.environ.get('TRADER_CLOUD') == 'true':
        raise ValueError('Cloud paper credentials are missing')
    else:
        c = tomllib.loads((Path.home()/'.codex/config.toml').read_text(encoding='utf-8'))['mcp_servers']['alpaca_paper']['env']
    if c.get('ALPACA_PAPER_TRADE') != 'true' or not all(c.get(k) for k in keys):
        raise ValueError('Complete paper credentials required')
    return c


def utc():
    return dt.datetime.now(dt.timezone.utc)


def instant(value):
    result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Time must include a UTC offset')
    return result


def save(path, value):
    temp = path.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as f:
        json.dump(value, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    temp.replace(path)
    if os.name != 'nt':
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


class Broker:
    def __init__(self):
        c = credentials()
        self.headers = {'APCA-API-KEY-ID': c['ALPACA_API_KEY'],
                        'APCA-API-SECRET-KEY': c['ALPACA_SECRET_KEY'],
                        'Content-Type': 'application/json'}

    def call(self, path, method='GET', body=None, market_data=False):
        # Never accept an endpoint from a plan or environment variable.
        if market_data and method != 'GET':
            raise ValueError('Market data is read only')
        base = 'https://data.alpaca.markets/v2' if market_data else 'https://paper-api.alpaca.markets/v2'
        req = urllib.request.Request(base+path,
            headers=self.headers, method=method,
            data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                data = response.read()
                return json.loads(data) if data else None
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and method == 'GET':
                return None
            raise RuntimeError('Paper API HTTP '+str(exc.code)) from None

    def by_client(self, cid):
        return self.call('/orders:by_client_order_id?client_order_id='+urllib.parse.quote(cid))


def validate(p):
    if p.get('paper') is not True or p.get('mode') not in {'armed', 'monitor_only'}:
        raise ValueError('Paper plan with armed or monitor_only mode required')
    if not re.fullmatch(r'[A-Z]{1,5}', p['symbol']):
        raise ValueError('Invalid stock symbol')
    for key in ('client_order_id', 'exit_client_order_id'):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,48}', p[key]):
            raise ValueError('Invalid client ID')
    if p['client_order_id'] == p['exit_client_order_id']:
        raise ValueError('Entry and exit IDs must differ')
    q, entry, stop, target = (D(str(p[k])) for k in ('qty', 'entry', 'stop', 'target'))
    if not all(x.is_finite() for x in (q, entry, stop, target)):
        raise ValueError('Nonfinite plan value')
    if q != q.to_integral_value() or q <= 0 or not 0 < stop < entry < target:
        raise ValueError('Whole long shares and stop < entry < target required')
    if q*entry > 5000 or q*(entry-stop) > 100:
        raise ValueError('Plan exceeds $5000 capital or $100 planned risk')
    if not instant(p['entry_after']) < instant(p['cancel_at']) < instant(p['flatten_at']) < instant(p['deadline']):
        raise ValueError('Invalid time sequence')
    if not p.get('authorization'):
        raise ValueError('Record the user authorization')


class Engine:
    def __init__(self, broker, plan, state, persist):
        validate(plan)
        self.b, self.p, self.s, self.persist = broker, plan, state, persist
        fingerprint = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        if state.get('fingerprint', fingerprint) != fingerprint:
            raise ValueError('Plan changed: restore original plan before continuing')
        state['fingerprint'] = fingerprint

    def position(self):
        return self.b.call('/positions/'+self.p['symbol'])

    def active(self, orders):
        return [o for o in orders if o['status'] not in TERMINAL]

    def cancel(self, orders):
        for o in self.active(orders):
            self.b.call('/orders/'+o['id'], 'DELETE')

    def commit(self, **values):
        self.s.update(values)
        self.persist(self.s)

    def step(self, now):
        p, b = self.p, self.b
        parent = b.by_client(p['client_order_id'])
        if parent is None:
            if self.s.get('entry_attempted'):
                return 'attention: entry response uncertain; reconcile, do not resubmit'
            if p['mode'] != 'armed' or now >= instant(p['cancel_at']):
                return 'idle: no entry exists; plan cannot submit'
            if not entries_enabled() or (ROOT/'PAUSE_ENTRIES').exists():
                return 'idle: entries paused'
            if now < instant(p['entry_after']):
                return 'waiting_for_entry_window'
            clock = b.call('/clock')
            if not clock['is_open']:
                return 'waiting_for_market'
            if instant(clock['next_close']) < instant(p['deadline']):
                raise ValueError('Deadline exceeds exchange session; revise plan')
            if b.call('/positions') or b.call('/orders?status=open'):
                return 'attention: entry requires an empty paper account'
            acct = b.call('/account')
            if acct['status'] != 'ACTIVE' or acct['trading_blocked'] or acct['account_blocked'] or D(acct['cash']) < D(str(p['qty']))*D(str(p['entry'])):
                return 'attention: account or cash check failed'
            snap = b.call('/stocks/'+p['symbol']+'/snapshot?feed=iex',market_data=True)
            quote, trade = snap.get('latestQuote'),snap.get('latestTrade')
            if not quote or not trade or any(not 0 <= (now-instant(x['t'])).total_seconds() <= 60 for x in (quote,trade)):
                return 'waiting_for_fresh_quote'
            ask, bid = D(str(quote['ap'])),D(str(quote['bp']))
            if not 0 < bid <= ask or (ask-bid)/ask > D('.001'):
                return 'waiting_for_tight_spread'
            if not D(str(p['stop'])) < D(str(trade['p'])) < D(str(p['target'])):
                return 'waiting_for_valid_price'
            # Persist before POST. Uncertain POSTs are never blindly repeated.
            self.commit(entry_attempted=True)
            b.call('/orders', 'POST', dict(symbol=p['symbol'], qty=str(p['qty']), side='buy',
                type='limit', limit_price=str(p['entry']), time_in_force='day', order_class='bracket',
                extended_hours=False, client_order_id=p['client_order_id'],
                take_profit={'limit_price':str(p['target'])}, stop_loss={'stop_price':str(p['stop'])}))
            return 'entry_submitted'

        parent = b.call('/orders/'+parent['id']+'?nested=true')
        legs = parent.get('legs') or []
        if (parent['symbol'] != p['symbol'] or parent['side'] != 'buy'
                or D(parent['qty']) != D(str(p['qty']))
                or D(parent['limit_price']) != D(str(p['entry']))
                or parent['order_class'] != 'bracket'):
            raise ValueError('Broker entry differs from authorized plan')
        if any(x['symbol'] != p['symbol'] or x['side'] != 'sell' for x in legs):
            raise ValueError('Unexpected bracket leg')
        exit_order = b.by_client(p['exit_client_order_id'])
        if exit_order and (exit_order['symbol'] != p['symbol'] or exit_order['side'] != 'sell'):
            raise ValueError('Exit client ID collision')
        filled = D(parent['filled_qty'])
        sold = sum((D(x['filled_qty']) for x in legs), D(0))
        if exit_order:
            sold += D(exit_order['filled_qty'])
        pos = self.position()
        qty = D(pos['qty']) if pos else D(0)
        owned = filled-sold
        if qty < 0 or qty > D(str(p['qty'])) or (pos and pos['side'] != 'long'):
            return 'attention: unexpected position; no sell submitted'
        orders = [parent]+legs+([exit_order] if exit_order else [])
        self.commit(entry_status=parent['status'], filled_qty=str(filled), position_qty=str(qty),
                    order_ids=[x['id'] for x in orders])
        if not qty and not self.active(orders) and owned == 0:
            return 'complete_flat'
        if qty != owned:
            return 'attention: position and fills disagree; waiting for reconciliation'
        exits_valid = (len(legs) == 2 and all(x['status'] not in TERMINAL for x in legs)
            and any(x.get('stop_price') and D(x['stop_price']) == D(str(p['stop'])) for x in legs)
            and any(x.get('limit_price') and D(x['limit_price']) == D(str(p['target'])) for x in legs))
        close = (self.s.get('closing') or now >= instant(p['flatten_at'])
            or 0 < filled < D(str(p['qty'])) or (qty > 0 and not exits_valid))
        if close:
            self.commit(closing=True)
            # In a closed market retain any working protection; report missed deadline.
            if qty and not b.call('/clock')['is_open']:
                return 'attention: market closed with position; awaiting next open'
            self.cancel([parent]+legs)
            parent = b.call('/orders/'+parent['id']+'?nested=true')
            legs = parent.get('legs') or []
            if self.active([parent]+legs):
                return 'canceling_before_exit'
            pos = self.position()
            qty = D(pos['qty']) if pos else D(0)
            exit_order = b.by_client(p['exit_client_order_id'])
            if exit_order:
                if exit_order['status'] in {'canceled','expired','rejected'} and qty:
                    return 'attention: exit failed; manual reconciliation required'
                return 'closing' if qty or exit_order['status'] not in TERMINAL else 'complete_flat'
            owned = D(parent['filled_qty'])-sum((D(x['filled_qty']) for x in legs),D(0))
            if qty != owned or qty < 0 or qty > D(str(p['qty'])):
                return 'attention: changed position; no sell submitted'
            if qty == 0:
                return 'complete_flat'
            known = {x['id'] for x in [parent]+legs}
            opened = b.call('/orders?status=open&symbols='+p['symbol'])
            if any(x['id'] not in known for x in opened):
                return 'attention: unrelated order on same symbol; no sell submitted'
            if self.s.get('exit_attempted'):
                return 'attention: exit response uncertain; reconcile, do not resubmit'
            self.commit(exit_attempted=True)
            b.call('/orders','POST',dict(symbol=p['symbol'],side='sell',qty=str(qty),
                type='market',time_in_force='day',client_order_id=p['exit_client_order_id']))
            return 'exit_submitted'
        if not filled and now >= instant(p['cancel_at']):
            self.cancel([parent]+legs)
            return 'canceling_unfilled'
        return 'monitoring'


def keep_awake(active):
    if os.name == 'nt':
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001 if active else 0x80000000)


def acquire_lock(path):
    lock = path.open('a+b')
    lock.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return None
    return lock


def initialize_state():
    if os.environ.get('TRADER_CLOUD') == 'true':
        if os.environ.get('PAPER_ENTRIES_ENABLED') not in {'true', 'false'}:
            raise ValueError('Cloud requires explicit PAPER_ENTRIES_ENABLED=true or false')
        if os.environ.get('TRADER_STORAGE') != 'broker':
            mount = Path(os.environ.get('TRADER_DISK_MOUNT', '/var/data'))
            if ROOT == SOURCE or not ROOT.is_relative_to(mount.resolve()) or not os.path.ismount(mount):
                raise ValueError('Cloud requires a mounted persistent disk for all state')
    ROOT.mkdir(parents=True, exist_ok=True)


def seed_state():
    # Never overwrite live plans, daily reservations or state during a deploy.
    if not (ROOT/'strategy.json').exists():
        save(ROOT/'strategy.json', json.loads((SOURCE/'strategy.json').read_text()))


def check_connection():
    broker = Broker()
    account = broker.call('/account')
    clock = broker.call('/clock')
    positions = broker.call('/positions')
    orders = broker.call('/orders?status=open')
    return dict(paper=True,account_status=account['status'],market_open=clock['is_open'],
                position_count=len(positions),open_order_count=len(orders),
                entries_enabled=entries_enabled())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--check', action='store_true', help='Read-only API check; no order mutations')
    args = parser.parse_args()
    if args.check:
        print(json.dumps(check_connection()))
        return
    initialize_state()
    # OS lock is automatically released even after a crash. No stale PID lock.
    lock = acquire_lock(ROOT/'runner.lock')
    if lock is None:
        return
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    previous = None
    last_log = 0
    try:
        seed_state()
        if os.environ.get('TRADER_STORAGE') == 'broker':
            from recovery import recover
            recover(Broker(), ROOT, utc())
        while not stop.is_set():
            active = False
            try:
                plan_path = ROOT/'plan.json'
                if not plan_path.exists():
                    status = 'idle: no active plan'
                else:
                    p = json.loads(plan_path.read_text(encoding='utf-8'))
                    validate(p)
                    state_path = ROOT/('state-'+p['client_order_id']+'.json')
                    state = json.loads(state_path.read_text()) if state_path.exists() else {}
                    engine = Engine(Broker(), p, state, lambda s: save(state_path,s))
                    active = True
                    status = engine.step(utc())
                    engine.commit(run_status=status)
                    active = status != 'complete_flat' and not status.startswith('idle:')
                # Selection runs only when the previous plan is flat or never entered.
                if status == 'complete_flat' or status.startswith('idle:'):
                    from strategy import select_next
                    selection = select_next(Broker(), ROOT, utc())
                    if selection:
                        status = selection
                        active = selection in {'scanning', 'plan_selected'} or selection.startswith('attention:')
            except Exception as exc:
                # Do not log HTTP headers, secrets, arbitrary response bodies or URLs.
                status = 'attention: '+(str(exc) if isinstance(exc,(ValueError,RuntimeError)) else type(exc).__name__)
                active = True
            snapshot = dict(updated_at=utc().isoformat(),pid=os.getpid(),paper=True,status=status,
                            codex_required=False,needs_attention=status.startswith('attention:'))
            save(ROOT/'status.json',snapshot)
            if status != previous:
                with (ROOT/'events.jsonl').open('a',encoding='utf-8') as f:
                    f.write(json.dumps(snapshot)+'\n')
                previous = status
                print(json.dumps(snapshot), flush=True)
                last_log = time.monotonic()
            elif time.monotonic()-last_log >= 300:
                print(json.dumps(snapshot), flush=True)
                last_log = time.monotonic()
            keep_awake(active)
            if args.once:
                print(json.dumps(snapshot))
                return
            stop.wait(5 if active else 60)
    finally:
        keep_awake(False)
        lock.close()


if __name__ == '__main__':
    main()
