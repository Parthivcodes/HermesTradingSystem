"""Free Render HTTP host + supervised runner. No public trading controls."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parent
stop=threading.Event()
child=None


def supervise():
    global child
    while not stop.is_set():
        # Missing credentials leaves a usable setup page, never a trading process.
        if not all(os.environ.get(k) for k in ('ALPACA_API_KEY','ALPACA_SECRET_KEY')):
            stop.wait(15)
            continue
        child=subprocess.Popen([sys.executable,'-u',str(ROOT/'runner.py')])
        while child.poll() is None and not stop.wait(1):
            pass
        if stop.is_set():
            child.terminate()
            try:child.wait(timeout=20)
            except subprocess.TimeoutExpired:child.kill()
        else:
            print('Paper runner exited; retrying broker reconciliation in 30 seconds',flush=True)
            stop.wait(30)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        running=child is not None and child.poll() is None
        payload=dict(service='Alpaca paper trader',hosting='Render Free',
            runner_process='running' if running else 'not running',
            entries_enabled=os.environ.get('PAPER_ENTRIES_ENABLED')=='true',
            capital_limit=5000,planned_risk_limit=100,
            limitation='Render Free sleeps after inactivity; timed exits are not guaranteed.')
        if self.path not in ('/','/healthz'):
            self.send_error(404);return
        body=json.dumps(payload).encode()
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers();self.wfile.write(body)
    def log_message(self,*args):pass


if __name__=='__main__':
    os.environ.setdefault('TRADER_STATE_DIR','/tmp/paper-trader')
    os.environ.setdefault('TRADER_CLOUD','true')
    os.environ.setdefault('TRADER_STORAGE','broker')
    os.environ.setdefault('PAPER_ENTRIES_ENABLED','false')
    signal.signal(signal.SIGTERM,lambda *_:stop.set())
    signal.signal(signal.SIGINT,lambda *_:stop.set())
    thread=threading.Thread(target=supervise,daemon=True);thread.start()
    server=ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT','10000'))),Handler)
    server.timeout=1
    while not stop.is_set():server.handle_request()
    server.server_close();thread.join(timeout=25)
