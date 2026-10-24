import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
(ROOT/'.test-temp').mkdir(exist_ok=True)
sys.path.insert(0,str(ROOT/'trader/standalone'))
from recovery import recover
from runner import instant, validate


class Broker:
    def __init__(self):
        self.order=dict(id='parent',client_order_id='auto-orb-20261023',symbol='MSFT',side='buy',
            qty='7',filled_qty='7',limit_price='522.22',order_class='bracket',status='filled',
            created_at='2026-10-23T14:00:00Z',legs=[
                dict(id='s',type='stop',status='new',filled_qty='0',stop_price='519.00'),
                dict(id='t',type='limit',status='new',filled_qty='0',limit_price='528.66')])
        self.positions=[{'symbol':'MSFT','qty':'7','side':'long'}]
    def call(self,path):
        if path.startswith('/orders?status=all'):return [self.order]
        if path.startswith('/orders/parent'):return self.order
        if path.startswith('/orders?status=open'):return [self.order]
        if path=='/positions':return self.positions
        if path.startswith('/calendar?'):return [{'close':'16:00'}]
        raise AssertionError(path)
    def by_client(self,cid):return None


class RecoveryTests(unittest.TestCase):
    def test_recovers_bracket_after_all_cache_is_lost(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.test-temp') as d:
            path=Path(d)
            recover(Broker(),path,instant('2026-10-23T18:00:00Z'))
            p=json.loads((path/'plan.json').read_text())
            validate(p)
            self.assertEqual(p['mode'],'monitor_only')
            self.assertEqual(p['qty'],7)
            self.assertEqual(instant(p['deadline']),instant('2026-10-23T19:55:00Z'))
            self.assertEqual(p['exit_client_order_id'],'auto-orb-20261023-exit')

    def test_unsafe_or_missing_bracket_does_not_reconstruct(self):
        for invalid in ('missing_stop','excess_risk','unknown_position'):
            b=Broker()
            if invalid=='missing_stop':b.order['legs'][0].pop('stop_price')
            if invalid=='excess_risk':b.order['legs'][0]['stop_price']='400'
            if invalid=='unknown_position':b.positions.append({'symbol':'AAPL'})
            with tempfile.TemporaryDirectory(dir=ROOT/'.test-temp') as d:
                with self.assertRaises((ValueError,RuntimeError)):
                    recover(b,Path(d),instant('2026-10-23T18:00:00Z'))
                self.assertFalse((Path(d)/'plan.json').exists())

    def test_preserves_existing_intents_and_plan(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.test-temp') as d:
            p=Path(d)/'plan.json';p.write_text('{"existing":true}')
            recover(None,Path(d),instant('2026-10-23T18:00:00Z'))
            self.assertEqual(json.loads(p.read_text()),{'existing':True})


if __name__=='__main__':unittest.main()
