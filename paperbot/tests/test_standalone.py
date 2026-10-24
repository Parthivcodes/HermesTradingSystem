"""Offline fault and risk tests; never access credentials or the network."""
import copy
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import os

ROOT = Path(__file__).resolve().parents[1]/'trader'/'standalone'
(ROOT.parents[1]/'.test-temp').mkdir(exist_ok=True)
sys.path.insert(0,str(ROOT))
from runner import Engine, instant, validate, credentials, entries_enabled, initialize_state, acquire_lock, seed_state
from strategy import candidate, select_next

BASE = json.loads((ROOT/'plan.json').read_text())
NOW = instant('2026-10-23T19:54:10Z')


class FakeBroker:
    def __init__(self, filled='7', qty='7'):
        self.parent = dict(id='parent',symbol='MSFT',side='buy',qty='7',limit_price='522.22',
            order_class='bracket',filled_qty=filled,status='filled' if filled=='7' else 'new',legs=[
            dict(id='stop',symbol='MSFT',side='sell',status='new',filled_qty='0',stop_price='519'),
            dict(id='target',symbol='MSFT',side='sell',status='new',filled_qty='0',limit_price='528.66')])
        self.pos = dict(qty=qty,side='long') if qty!='0' else None
        self.exit = None
        self.calls = []
        self.open = True
        self.uncertain = False
        self.delay_cancel = False

    def by_client(self,cid):
        return copy.deepcopy(self.exit if cid==BASE['exit_client_order_id'] else self.parent)

    def call(self,path,method='GET',body=None,market_data=False):
        self.calls.append((path,method,body))
        if method=='DELETE':
            if not self.delay_cancel:
                for o in [self.parent]+self.parent['legs']:
                    if path=='/orders/'+o['id']:o['status']='canceled'
            return None
        if method=='POST':
            if self.uncertain:raise TimeoutError()
            self.exit=dict(id='exit',symbol='MSFT',side='sell',status='new',filled_qty='0')
            return self.exit
        if path=='/clock':return dict(is_open=self.open,next_close='2026-10-23T20:00:00Z')
        if path=='/positions':return []
        if path=='/account':return dict(status='ACTIVE',trading_blocked=False,account_blocked=False,cash='5000')
        if path.startswith('/stocks/'):
            return dict(latestQuote=dict(t='2026-10-23T18:30:00Z',ap=522.22,bp=522.20),latestTrade=dict(t='2026-10-23T18:30:00Z',p=522.21))
        if path.startswith('/positions/'):return copy.deepcopy(self.pos)
        if path.startswith('/orders?'):return []
        if path.startswith('/orders/parent'):return copy.deepcopy(self.parent)
        raise AssertionError(path)


class ExecutorTests(unittest.TestCase):
    def engine(self,b,state=None,plan=None):
        return Engine(b,plan or copy.deepcopy(BASE),state if state is not None else {},lambda s:None)

    def test_risk_and_budget_rejected(self):
        for change in ({'qty':100},{'qty':7,'stop':'500'},{'paper':False},{'qty':0},{'qty':1.5},{'entry':'NaN'}):
            p=dict(BASE,**change)
            with self.assertRaises(ValueError):validate(p)

    def test_exit_cancels_before_sell_and_resumes(self):
        b=FakeBroker(); state={}
        self.assertEqual(self.engine(b,state).step(NOW),'exit_submitted')
        writes=[x for x in b.calls if x[1]!='GET']
        self.assertEqual([x[1] for x in writes],['DELETE','DELETE','POST'])
        self.assertEqual(writes[-1][2]['qty'],'7')
        self.assertEqual(self.engine(b,state).step(NOW),'closing')
        self.assertEqual(sum(x[1]=='POST' for x in b.calls),1)

    def test_waits_for_cancellation(self):
        b=FakeBroker();b.delay_cancel=True
        self.assertEqual(self.engine(b).step(NOW),'canceling_before_exit')
        self.assertFalse(any(x[1]=='POST' for x in b.calls))

    def test_partial_fill_closes_actual_quantity(self):
        b=FakeBroker('2','2')
        self.assertEqual(self.engine(b).step(instant('2026-10-23T18:30:00Z')),'exit_submitted')
        self.assertEqual([x for x in b.calls if x[1]=='POST'][0][2]['qty'],'2')

    def test_no_short_or_unowned_sell(self):
        for qty in ('-1','8','3'):
            b=FakeBroker(qty=qty)
            self.assertTrue(self.engine(b).step(NOW).startswith('attention:'))
            self.assertFalse(any(x[1]!='GET' for x in b.calls))

    def test_market_closed_keeps_protection(self):
        b=FakeBroker();b.open=False
        self.assertIn('market closed',self.engine(b).step(NOW))
        self.assertFalse(any(x[1]!='GET' for x in b.calls))

    def test_exit_timeout_does_not_duplicate(self):
        b=FakeBroker();b.uncertain=True;state={}
        with self.assertRaises(TimeoutError):self.engine(b,state).step(NOW)
        self.assertIn('uncertain',self.engine(b,state).step(NOW))
        self.assertEqual(sum(x[1]=='POST' for x in b.calls),1)

    def test_expired_unfilled_is_complete(self):
        b=FakeBroker('0','0');b.parent['status']='expired'
        for o in b.parent['legs']:o['status']='canceled'
        self.assertEqual(self.engine(b).step(NOW),'complete_flat')
        self.assertFalse(any(x[1]!='GET' for x in b.calls))

    def test_historical_plan_cannot_reenter(self):
        b=FakeBroker();b.parent=None
        self.assertTrue(self.engine(b).step(NOW).startswith('idle:'))
        self.assertFalse(b.calls)

    def test_plan_changes_rejected_after_restart(self):
        b=FakeBroker();state={};self.engine(b,state)
        with self.assertRaises(ValueError):self.engine(b,state,dict(BASE,target='530'))

    def test_entry_intent_prevents_repeat_after_timeout(self):
        b=FakeBroker();b.parent=None;b.uncertain=True;state={};p=dict(BASE,mode='armed')
        with self.assertRaises(TimeoutError):self.engine(b,state,p).step(instant('2026-10-23T18:30:00Z'))
        self.assertIn('uncertain',self.engine(b,state,p).step(instant('2026-10-23T18:31:00Z')))
        self.assertEqual(sum(x[1]=='POST' for x in b.calls),1)


class StrategyTests(unittest.TestCase):
    def fixture(self):
        start=instant('2026-10-23T13:30:00Z');now=start+dt.timedelta(minutes=20,seconds=10)
        bars=[dict(t=(start+dt.timedelta(minutes=i*5)).isoformat(),h=101,l=100,c=100.8,v=100,vw=100.5) for i in range(4)]
        bars[-1].update(h=101.2,c=101.1,v=150,vw=101)
        snap=dict(latestQuote=dict(t=now.isoformat(),ap=101.15,bp=101.10),latestTrade=dict(t=now.isoformat(),p=101.12))
        return bars,snap,start,now

    def test_signal_sizing(self):
        bars,snap,start,now=self.fixture()
        p=candidate('MSFT',bars,snap,start,now)
        self.assertIsNotNone(p)
        self.assertLessEqual(p['qty']*float(p['entry']),3750)
        self.assertLessEqual(p['qty']*(float(p['entry'])-float(p['stop'])),90)

    def test_stale_and_wide_spread_and_missing_range_rejected(self):
        bars,snap,start,now=self.fixture()
        self.assertIsNone(candidate('MSFT',bars,snap,start,now+dt.timedelta(minutes=2)))
        snap['latestQuote']['bp']=99
        self.assertIsNone(candidate('MSFT',bars,snap,start,now))
        bars,snap,start,now=self.fixture()
        self.assertIsNone(candidate('MSFT',bars[1:],snap,start,now))

    def test_daily_selection_recovered_without_second_trade(self):
        b=FakeBroker()
        with tempfile.TemporaryDirectory(dir=ROOT.parents[1]/'.test-temp') as d:
            root=Path(d)
            (root/'strategy.json').write_text(json.dumps(dict(enabled=True,paper=True)))
            (root/'selection-2026-10-23.json').write_text(json.dumps(BASE))
            self.assertEqual(select_next(b,root,NOW),'plan_selected')
            self.assertEqual(select_next(b,root,NOW),'idle: daily trade allowance used')
            self.assertTrue(all(x[0]=='/clock' for x in b.calls))

    def test_full_selection_is_dated_and_durable(self):
        bars,snap,start,now=self.fixture()
        class Market:
            def call(self,path,market_data=False):
                if path=='/clock':return dict(is_open=True)
                if path.startswith('/calendar?'):return [dict(open='09:30',close='16:00')]
                if path in ('/positions','/orders?status=open'):return []
                if path.startswith('/orders?'):return []
                if path.startswith('/stocks/bars?'):return dict(bars={'MSFT':bars},next_page_token=None)
                if path.startswith('/stocks/snapshots?'):return {'MSFT':snap}
                if path=='/assets/MSFT':return dict(tradable=True,status='active')
                raise AssertionError(path)
        with tempfile.TemporaryDirectory(dir=ROOT.parents[1]/'.test-temp') as d:
            root=Path(d)
            (root/'strategy.json').write_text(json.dumps(dict(enabled=True,paper=True,authorization='test')))
            self.assertEqual(select_next(Market(),root,now),'plan_selected')
            p=json.loads((root/'plan.json').read_text())
            validate(p)
            self.assertEqual(instant(p['deadline']),instant('2026-10-23T19:55:00Z'))
            self.assertEqual(instant(p['cancel_at']),now+dt.timedelta(minutes=3))
            self.assertEqual(select_next(Market(),root,now+dt.timedelta(minutes=1)),'idle: daily trade allowance used')


class CloudTests(unittest.TestCase):
    def test_environment_credentials_require_explicit_paper(self):
        with patch.dict(os.environ,{'ALPACA_API_KEY':'test-key','ALPACA_SECRET_KEY':'test-secret','ALPACA_PAPER_TRADE':'false'}):
            with self.assertRaises(ValueError):credentials()
        with patch.dict(os.environ,{'ALPACA_API_KEY':'test-key','ALPACA_SECRET_KEY':'test-secret','ALPACA_PAPER_TRADE':'true'}):
            self.assertEqual(credentials()['ALPACA_API_KEY'],'test-key')

    def test_partial_environment_does_not_fall_back(self):
        with patch.dict(os.environ,{'ALPACA_API_KEY':'test-key','ALPACA_SECRET_KEY':'','ALPACA_PAPER_TRADE':'true'}):
            with self.assertRaises(ValueError):credentials()

    def test_cloud_entries_disabled_blocks_armed_plan(self):
        b=FakeBroker();b.parent=None
        with patch.dict(os.environ,{'PAPER_ENTRIES_ENABLED':'false'}):
            engine=Engine(b,dict(BASE,mode='armed'),{},lambda s:None)
            self.assertEqual(engine.step(instant('2026-10-23T18:30:00Z')),'idle: entries paused')
            self.assertFalse(b.calls)

    def test_disabling_entries_does_not_disable_exit(self):
        b=FakeBroker()
        with patch.dict(os.environ,{'PAPER_ENTRIES_ENABLED':'false'}):
            self.assertEqual(Engine(b,BASE,{},lambda s:None).step(NOW),'exit_submitted')

    def test_cloud_refuses_nonpersistent_storage(self):
        with patch.dict(os.environ,{'TRADER_CLOUD':'true','TRADER_DISK_MOUNT':'/nonexistent-paper-disk'}):
            with self.assertRaises(ValueError):initialize_state()

    def test_process_lock_excludes_second_owner(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parents[1]/'.test-temp') as d:
            path=Path(d)/'lock'
            first=acquire_lock(path)
            self.assertIsNotNone(first)
            try:self.assertIsNone(acquire_lock(path))
            finally:first.close()
            again=acquire_lock(path)
            self.assertIsNotNone(again)
            again.close()

    def test_existing_settings_not_replaced_on_deploy(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parents[1]/'.test-temp') as d:
            root=Path(d)
            existing={'enabled':False,'paper':True}
            (root/'strategy.json').write_text(json.dumps(existing))
            with patch('runner.ROOT',root):seed_state()
            self.assertEqual(json.loads((root/'strategy.json').read_text()),existing)

    def test_broker_history_blocks_second_trade_after_disk_loss(self):
        class History:
            def call(self,path):
                if path=='/clock':return {'is_open':True}
                if path.startswith('/calendar'):return [{'open':'09:30','close':'16:00'}]
                if path in ('/positions','/orders?status=open'):return []
                if path.startswith('/orders?'):return [{'client_order_id':'auto-orb-20261023-MSFT'}]
                raise AssertionError(path)
        with tempfile.TemporaryDirectory(dir=ROOT.parents[1]/'.test-temp') as d:
            root=Path(d)
            (root/'strategy.json').write_text(json.dumps({'enabled':True,'paper':True}))
            status=select_next(History(),root,instant('2026-10-23T14:00:00Z'))
            self.assertEqual(status,'idle: broker records show daily trade allowance used')


if __name__=='__main__':unittest.main()
