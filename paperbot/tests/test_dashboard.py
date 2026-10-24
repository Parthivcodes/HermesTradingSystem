import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]/'trader/standalone'
sys.path.insert(0,str(ROOT))
import dashboard
import web


class FakeBroker:
    def __init__(self):self.paths=[]
    def call(self,path):
        self.paths.append(path)
        if path=='/clock':return {'is_open':False}
        if path=='/positions':return [{'symbol':'MSFT','qty':'2','unrealized_pl':'3'},{'symbol':'OTHER','qty':'99'}]
        return [dict(id='entry',client_order_id='auto-orb-20261026',symbol='MSFT',side='buy',
            qty='2',filled_qty='2',filled_avg_price='500',created_at='2026-10-26T14:00:00Z',
            filled_at='2026-10-26T14:00:01Z',updated_at='2026-10-26T14:00:01Z',status='filled',
            legs=[dict(id='stop',symbol='MSFT',side='sell',type='stop',stop_price='495',
                filled_qty='0',qty='2',status='new',created_at='2026-10-26T14:00:01Z')]),
            dict(id='unrelated',client_order_id='manual',symbol='OTHER')]


class DashboardTests(unittest.TestCase):
    def test_auth_rejects_missing_expired_and_tampered_sessions(self):
        with patch.dict(os.environ,{'DAYTRADER_DASHBOARD_PASSWORD':'test-only-access'}):
            valid=web.session_token(int(time.time()+60))
            self.assertTrue(web.authenticated('daytrader_session='+valid))
            self.assertFalse(web.authenticated('daytrader_session='+valid+'x'))
            self.assertFalse(web.authenticated('daytrader_session='+web.session_token(int(time.time()-1))))
            self.assertFalse(web.authenticated(None))
        with patch.dict(os.environ,{'DAYTRADER_DASHBOARD_PASSWORD':''}):
            self.assertFalse(web.authenticated('daytrader_session='+valid))

    def test_broker_data_is_read_only_scoped_and_cached(self):
        dashboard.cached=None
        broker=FakeBroker()
        temp_root=ROOT.parents[1]/'.test-temp'
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as root:
            result=dashboard.snapshot(root,broker)
            self.assertEqual([p['symbol'] for p in result['positions']],['MSFT'])
            self.assertEqual(len(result['orders']),2)
            self.assertEqual(result['events'][0]['kind'],'buy')
            self.assertIn('Stop loss',[o['role'] for o in result['orders']])
            count=len(broker.paths)
            self.assertEqual(dashboard.snapshot(root,broker),result)
            self.assertEqual(len(broker.paths),count)
            self.assertTrue(all(p.startswith(('/clock','/positions','/orders?')) for p in broker.paths))
        dashboard.cached=None


if __name__=='__main__':unittest.main()
