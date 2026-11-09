#!/usr/bin/env python3
import base64,json,os,pathlib,re,socket,ssl,struct,subprocess,time
from urllib.request import Request,build_opener,ProxyHandler,HTTPSHandler,HTTPRedirectHandler
from urllib.error import HTTPError
base=pathlib.Path(__file__).parent
login=json.loads((base/'login.json').read_text())
auth='Basic '+base64.b64encode((login['username']+':'+login['password']).encode()).decode()
ctx=ssl.create_default_context(cafile=str(base/'caddy-local-root.crt'))
class NoRedirect(HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
op=build_opener(ProxyHandler({}),HTTPSHandler(context=ctx),NoRedirect())

def get(path,authenticated=True,extra=None):
 headers={'Authorization':auth} if authenticated else {}
 if extra:headers.update(extra)
 try:r=op.open(Request('https://192.168.0.168'+path,headers=headers),timeout=10)
 except HTTPError as e:r=e
 return r

def exact(s,n):
 out=b''
 while len(out)<n:
  b=s.recv(n-len(out))
  if not b:raise EOFError()
  out+=b
 return out

def ws_connect(origin,authenticated=True):
 raw=socket.create_connection(('192.168.0.168',443),timeout=8)
 s=ctx.wrap_socket(raw,server_hostname='192.168.0.168')
 key=base64.b64encode(os.urandom(16)).decode()
 h=f'GET /pi/ws HTTP/1.1\r\nHost: 192.168.0.168\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: tty\r\nOrigin: {origin}\r\n'
 if authenticated:h+='Authorization: '+auth+'\r\n'
 s.sendall((h+'\r\n').encode());b=b''
 while b'\r\n\r\n' not in b:
  part=s.recv(1)
  if not part:break
  b+=part
 return s,b.split(b'\r\n',1)[0].decode(errors='replace')

def send(s,p,opcode=2):
 mask=os.urandom(4);n=len(p);h=bytes([0x80|opcode])
 if n<126:h+=bytes([0x80|n])
 elif n<65536:h+=bytes([0x80|126])+struct.pack('!H',n)
 else:h+=bytes([0x80|127])+struct.pack('!Q',n)
 s.sendall(h+mask+bytes(x^mask[i%4] for i,x in enumerate(p)))

for path in ['/','/global/health','/pi/','/pi/token','/pi/ws']:
 r=get(path,False);print('Unauthenticated',path,r.status);assert r.status==401;r.close()
r=get('/global/health');d=json.loads(r.read());print('OpenCode health',r.status,d.get('healthy'),d.get('version'));assert r.status==200 and d.get('healthy') is True
r=get('/');html=r.read().decode();print('OpenCode HTML',r.status,'title',re.findall(r'<title>(.*?)</title>',html));assert r.status==200 and '<title>OpenCode</title>' in html
for asset in re.findall(r'(?:src|href)="([^"]+)"',html):
 if asset.startswith('/') and re.search(r'\.(?:js|css)(?:\?|$)',asset):
  r=get(asset);n=len(r.read());print('OpenCode asset',r.status,n);assert r.status==200 and n>0
r=get('/pi');print('Pi canonical path',r.status,r.headers.get('Location'));assert r.status in (301,302,307,308) and r.headers.get('Location')=='/pi/';r.close()
r=get('/pi/');html=r.read().decode();print('Pi HTML',r.status,'ttyd' in html);assert r.status==200 and 'ttyd' in html
r=get('/pi/token');d=json.loads(r.read());print('Pi token endpoint',r.status,'token field present', 'token' in d);assert r.status==200 and 'token' in d
r=get('/global/event');print('OpenCode events',r.status,r.headers.get('Content-Type'));assert r.status==200 and 'text/event-stream' in r.headers.get('Content-Type','');line=r.readline();print('SSE first frame received',bool(line));assert line;r.close()
s,status=ws_connect('https://192.168.0.168',False);print('Unauthenticated WS',status);assert '401' in status;s.close()
s,status=ws_connect('https://other.invalid');print('Foreign-origin WS',status or 'connection rejected');assert '101' not in status;s.close()
pid=subprocess.check_output(['tmux','-L','agent-ui-test','display-message','-p','-t','pi-tui','#{pane_pid}'],text=True).strip()
size=subprocess.check_output(['tmux','-L','agent-ui-test','display-message','-p','-t','pi-tui','#{pane_width} #{pane_height}'],text=True).strip().split()
s,status=ws_connect('https://192.168.0.168');print('Authenticated Pi WS',status);assert '101' in status
send(s,json.dumps({'AuthToken':'','columns':int(size[0]),'rows':int(size[1])}).encode(),1)
s.settimeout(1.0);chunks=[]
for _ in range(50):
 try:
  a,b=exact(s,2);n=b&127
  if n==126:n=struct.unpack('!H',exact(s,2))[0]
  elif n==127:n=struct.unpack('!Q',exact(s,8))[0]
  mask=exact(s,4) if b&128 else None;p=exact(s,n)
  if mask:p=bytes(x^mask[i%4] for i,x in enumerate(p))
  if a&15==9:send(s,p,10);continue
  if a&15==8:break
  if p.startswith(b'0'):chunks.append(p[1:])
 except socket.timeout:break
out=b''.join(chunks);print('Pi live frames',len(chunks),'bytes',len(out),'session marker',b'agent-ui-test' in out);assert chunks and b'agent-ui-test' in out
send(s,struct.pack('!H',1000),8);s.close()
now=subprocess.check_output(['tmux','-L','agent-ui-test','display-message','-p','-t','pi-tui','#{pane_pid} #{pane_dead}'],text=True).strip()
print('Pi survives disconnect',now);assert now==pid+' 0'
print('LAN VERIFICATION PASSED; no Pi input or model prompts sent')
