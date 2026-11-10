#!/usr/bin/env python3
import socket,os,base64,struct,json
from urllib.request import build_opener,ProxyHandler,Request
op=build_opener(ProxyHandler({}))
r=op.open(Request('http://192.168.0.168/',headers={'Host':'ha.antonkos.xyz'}),timeout=12)
print('HA existing HTTP route',r.status);assert r.status==200;r.close()
s=socket.create_connection(('192.168.0.168',80),timeout=10)
k=base64.b64encode(os.urandom(16)).decode()
req=f'GET /api/websocket HTTP/1.1\r\nHost: ha.antonkos.xyz\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {k}\r\nSec-WebSocket-Version: 13\r\nOrigin: https://ha.antonkos.xyz\r\n\r\n'
s.sendall(req.encode());h=b''
while b'\r\n\r\n' not in h:
 x=s.recv(1)
 if not x:break
 h+=x
status=h.split(b'\r\n',1)[0].decode();print('HA WebSocket reconnect',status);assert '101' in status

def exact(n):
 b=b''
 while len(b)<n:
  a=s.recv(n-len(b))
  if not a:raise EOFError()
  b+=a
 return b
a,b=exact(2);n=b&127
if n==126:n=struct.unpack('!H',exact(2))[0]
elif n==127:n=struct.unpack('!Q',exact(8))[0]
mask=exact(4) if b&128 else None;p=exact(n)
if mask:p=bytes(x^mask[i%4] for i,x in enumerate(p))
d=json.loads(p);print('HA still requires login:',d.get('type'));assert d.get('type')=='auth_required';s.close()
print('HA REGRESSION CHECK PASSED; no HA login/session/control changes')
