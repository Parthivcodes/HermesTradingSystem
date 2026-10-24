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
import hashlib
import hmac
import secrets
from http.cookies import SimpleCookie, CookieError
from dashboard import snapshot

ROOT=Path(__file__).resolve().parent
stop=threading.Event()
child=None


def session_token(expiry):
    key=os.environ.get('DAYTRADER_DASHBOARD_PASSWORD','').encode()
    return str(expiry)+'.'+hmac.new(key,str(expiry).encode(),hashlib.sha256).hexdigest()


def authenticated(cookie):
    if not os.environ.get('DAYTRADER_DASHBOARD_PASSWORD'):
        return False
    try:
        cookies=SimpleCookie(cookie or '')
        token=cookies['daytrader_session'].value
        expiry=int(token.split('.')[0])
        return time.time()<expiry<=time.time()+43260 and hmac.compare_digest(token,session_token(expiry))
    except (KeyError,ValueError,CookieError):
        return False


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
    def respond(self,code,body,kind='application/json',cookie=None):
        if not isinstance(body,bytes):body=json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type',kind)
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
        if cookie:self.send_header('Set-Cookie',cookie)
        self.send_header('Content-Length',str(len(body)))
        self.end_headers();self.wfile.write(body)

    def do_POST(self):
        if self.path not in ('/login','/logout'):
            self.respond(404,{});return
        # JSON custom header prevents cross-site form login/logout.
        if self.headers.get('X-Daytrader')!='dashboard':
            self.respond(403,{});return
        if self.path=='/logout':
            self.respond(200,{},cookie='daytrader_session=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0');return
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:
            self.respond(400,{});return
        if not 0<length<=1024:
            self.respond(400,{});return
        try:password=json.loads(self.rfile.read(length)).get('password','')
        except (ValueError,AttributeError):password=''
        expected=os.environ.get('DAYTRADER_DASHBOARD_PASSWORD','')
        if not expected or not isinstance(password,str) or not secrets.compare_digest(password,expected):
            time.sleep(1)
            self.respond(401,{'error':'Incorrect access code'});return
        token=session_token(int(time.time()+43200))
        self.respond(200,{},cookie='daytrader_session='+token+'; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=43200')

    def do_GET(self):
        if self.path=='/':
            self.respond(200,(ROOT/'dashboard.html').read_bytes(),'text/html; charset=utf-8');return
        if self.path=='/api/state':
            if not authenticated(self.headers.get('Cookie')):
                self.respond(401,{'error':'Sign in to view paper trades'});return
            try:
                data=snapshot(os.environ.get('TRADER_STATE_DIR','/tmp/paper-trader'))
                data['entries_enabled']=os.environ.get('PAPER_ENTRIES_ENABLED')=='true'
                self.respond(200,data)
            except Exception:
                self.respond(503,{'error':'Broker update unavailable. Displayed data may be stale.'})
            return
        running=child is not None and child.poll() is None
        payload=dict(service='Daytrader',hosting='Render Free',
            runner_process='running' if running else 'not running',
            entries_enabled=os.environ.get('PAPER_ENTRIES_ENABLED')=='true',
            capital_limit=5000,planned_risk_limit=100,
            limitation='Render Free sleeps after inactivity; timed exits are not guaranteed.')
        if self.path!='/healthz':
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
