"""Real Unix worker API and unprivileged filesystem sandbox, synthetic data only."""
import json, os, select, socket, sqlite3, subprocess, sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/authority'))
from authority import connect_knowledge

@pytest.fixture
def instance(tmp_path):
    private=tmp_path/'private'; private.mkdir()
    db=private/'authority.sqlite'; secret=private/'curator-secret';secret.write_text('synthetic-curator-secret')
    s=connect_knowledge(str(db),'alpha');page=s.create_page('alpha','page','Title','Original synthetic body','owner');s.disconnect()
    sock=tmp_path/'worker.sock'
    p=subprocess.Popen([sys.executable,str(ROOT/'src/mcp/worker_service.py'),str(db),'alpha',str(sock)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        ready,_,_=select.select([p.stdout],[],[],5)
        assert ready and p.stdout.readline().strip()=='READY',p.stderr.read() if p.poll() is not None else 'service unavailable'
        yield db,secret,sock,page.revision
    finally:
        p.terminate();p.wait(timeout=5)

def rpc(sock,request):
    with socket.socket(socket.AF_UNIX) as c:
        c.settimeout(5);c.connect(str(sock));c.sendall(json.dumps(request).encode()+b'\n');c.shutdown(socket.SHUT_WR)
        chunks=[]
        while x:=c.recv(65536):chunks.append(x)
    return json.loads(b''.join(chunks))

def test_actual_read_proposal_and_durable_receipt(instance):
    db,secret,sock,rev=instance
    assert rpc(sock,{'tool':'wiki_page','args':{'page':'page'}})['result']['revision']==rev
    req={'tool':'wiki_propose','args':{'page':'page','baseRevision':rev,'changeKind':'replace','title':'Title','markdown':'New synthetic body','sources':[],'key':'stable-host-call'}}
    first=rpc(sock,req);assert first['result']['kind']=='pending'
    assert rpc(sock,req)==first
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT COUNT(*) FROM proposals').fetchone()[0]==1
        assert c.execute('SELECT revision FROM page_heads').fetchone()[0]==rev

@pytest.mark.parametrize('payload',[
 {'tool':'wiki_curator_decide','args':{}},
 {'tool':'wiki_recall_snapshot','args':{}},
 {'tool':'wiki_page','args':{'page':'page'},'principal':'curator'},
 {'tool':'wiki_page','args':{'page':'page','project':'other'}},
 {'tool':'wiki_page','args':{'page':'../../private/authority.sqlite'}},
 {'tool':'wiki_page','args':{'page':'page'},'database':'/etc/passwd'},
])
def test_forged_boundary_requests_denied(instance,payload):
    assert rpc(instance[2],payload)['error']=='request denied'

def test_worker_mount_cannot_read_database_or_secret(instance):
    db,secret,sock,rev=instance
    launcher=ROOT/'src/mcp/sandbox_worker.py'
    code="""import json,os,socket
paths=ATTACK_PATHS
for p in paths:
 try:open(p,'rb')
 except OSError:pass
 else:raise AssertionError('host file readable: '+p)
assert 'WIKI_BOUNDARY_SECRET_MARKER' not in os.environ
assert os.readlink('/proc/self/ns/net') != 'HOST_NET_NS'
assert not os.path.exists('/home/kos')
assert len(os.listdir('/proc'))>0
s=socket.socket(socket.AF_UNIX);s.connect('/run/wiki.sock');s.sendall(b'{"tool":"wiki_page","args":{"page":"page"}}\\n');s.shutdown(socket.SHUT_WR)
b=b''
while True:
 x=s.recv(65536)
 if not x:break
 b+=x
assert json.loads(b)['result']['page']=='page'
print('ISOLATED_READ_OK')
"""
    code=code.replace("ATTACK_PATHS",repr([str(db),str(secret),'/proc/1/root'+str(db)])).replace("HOST_NET_NS",os.readlink("/proc/self/ns/net"))
    result=subprocess.run([sys.executable,str(launcher),str(sock),'--','/usr/bin/python3','-c',code],env={**os.environ,'WIKI_BOUNDARY_SECRET_MARKER':'synthetic-must-not-leak'},capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='ISOLATED_READ_OK'

def test_deeply_nested_request_does_not_kill_service(instance):
    sock=instance[2]
    with socket.socket(socket.AF_UNIX) as c:
        c.settimeout(5);c.connect(str(sock));c.sendall(b'['*15000+b'0'+b']'*15000+b'\n');c.shutdown(socket.SHUT_WR)
        assert json.loads(c.recv(65536))['error']=='request denied'
    assert rpc(sock,{'tool':'wiki_page','args':{'page':'page'}})['result']['page']=='page'
