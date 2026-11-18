import json,os,select,socket,sqlite3,subprocess,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/mcp'))
sys.path.insert(0,str(ROOT/'src/authority'))
from host_journal import Journal
from authority import connect_knowledge
from recovery import backup, restore

SCOPE=dict(project='alpha',principal='worker',epoch='epoch-1')
def args(rev='revision'):
 return dict(page='page',baseRevision=rev,changeKind='replace',title='Title',markdown='Synthetic change',sources=[])
def test_identity_payload_scope_and_missing_fail_closed(tmp_path):
 path=tmp_path/'journal.sqlite'
 with pytest.raises(Exception): Journal(path,**SCOPE)
 Journal.enroll(path,**SCOPE)
 with pytest.raises(Exception): Journal.enroll(path,**SCOPE)
 j=Journal(path,**SCOPE)
 with pytest.raises(ValueError):j.prepare('', 'call',args())
 with pytest.raises(ValueError):j.prepare('session','',args())
 a=j.prepare('session','call',args()); assert j.prepare('session','call',args())==a
 with pytest.raises(ValueError):j.prepare('session','call',{**args(),'markdown':'changed'})
 with pytest.raises(ValueError):j.prepare('session','other',{**args(),'key':'model-key'})
 for name,value in [('project','beta'),('principal','curator'),('epoch','restored-epoch')]:
  with pytest.raises(ValueError):Journal(path,**{**SCOPE,name:value})
 # caller cannot mutate the persisted payload via the returned object
 a['args']['markdown']='tampered'
 assert j.prepare('session','call',args())['args']['markdown']=='Synthetic change'

@pytest.mark.parametrize('phase',['before-send','after-send'])
def test_real_kill_restart_preserves_key_and_exact_receipt(tmp_path,phase):
 db=tmp_path/'authority.sqlite';s=connect_knowledge(str(db),'alpha')
 page=s.create_page('alpha','page','Title','Original','owner');s.disconnect()
 with sqlite3.connect(db) as c:c.execute("UPDATE projects SET epoch='epoch-1'")
 sock=tmp_path/'worker.sock'
 server=subprocess.Popen([sys.executable,str(ROOT/'src/mcp/worker_service.py'),str(db),'alpha',str(sock)],stdout=subprocess.PIPE,text=True)
 child=None
 try:
  assert select.select([server.stdout],[],[],5)[0];assert server.stdout.readline().strip()=='READY'
  journal=tmp_path/'journal.sqlite';Journal.enroll(journal,**SCOPE)
  code='''import json,sys,time
from host_journal import Journal
j=Journal(sys.argv[1],project='alpha',principal='worker',epoch='epoch-1')
a=json.loads(sys.argv[3]);r=j.prepare('trusted-session','trusted-call',a)
if sys.argv[4]=='after-send': j.send(sys.argv[2],r)
print('BARRIER',flush=True)
time.sleep(60)
'''
  child=subprocess.Popen([sys.executable,'-c',code,str(journal),str(sock),json.dumps(args(page.revision)),phase],env={**os.environ,'PYTHONPATH':str(ROOT/'src/mcp')},stdout=subprocess.PIPE,text=True)
  assert select.select([child.stdout],[],[],10)[0];assert child.stdout.readline().strip()=='BARRIER'
  child.kill();child.wait(timeout=5)
  with sqlite3.connect(db) as c:assert c.execute('SELECT COUNT(*) FROM proposals').fetchone()[0]==(phase=='after-send')
  j=Journal(journal,**SCOPE);r=j.prepare('trusted-session','trusted-call',args(page.revision))
  restart="import json,sys;from host_journal import Journal;j=Journal(sys.argv[1],project='alpha',principal='worker',epoch='epoch-1');print(json.dumps(j.execute(sys.argv[2],'trusted-session','trusted-call',json.loads(sys.argv[3]))))"
  resumed=subprocess.run([sys.executable,'-c',restart,str(journal),str(sock),json.dumps(args(page.revision))],env={**os.environ,'PYTHONPATH':str(ROOT/'src/mcp')},capture_output=True,text=True,timeout=10,check=True)
  first=json.loads(resumed.stdout)
  assert first['result']['kind']=='pending'
  assert Journal(journal,**SCOPE).execute(str(sock),'trusted-session','trusted-call',args(page.revision))==first
  assert j.prepare('trusted-session','trusted-call',args(page.revision))==r
  with sqlite3.connect(db) as c:assert c.execute('SELECT COUNT(*) FROM proposals').fetchone()[0]==1
  saved=backup(str(db),'alpha',tmp_path/'snapshots')
  recovered=restore(saved['path'],tmp_path/'restored');assert recovered['success'],recovered
  server.terminate();server.wait(timeout=5)
  server=subprocess.Popen([sys.executable,str(ROOT/'src/mcp/worker_service.py'),recovered['path'],'alpha',str(sock)],stdout=subprocess.PIPE,text=True)
  assert select.select([server.stdout],[],[],5)[0];assert server.stdout.readline().strip()=='READY'
  # Even bypassing the handshake cannot replay an old-epoch prepared mutation.
  with pytest.raises(ValueError):j.send(str(sock),r)
  with pytest.raises(ValueError):j.execute(str(sock),'trusted-session','trusted-call',args(page.revision))
  with pytest.raises(ValueError):j.execute(str(sock),'trusted-session','fresh-call',args(page.revision))
  with sqlite3.connect(journal) as c:assert c.execute('SELECT COUNT(*) FROM calls').fetchone()[0]==1
 finally:
  if child and child.poll() is None:child.kill();child.wait()
  server.terminate();server.wait(timeout=5)


def test_concurrent_preparation(tmp_path):
 from concurrent.futures import ThreadPoolExecutor
 p=tmp_path/'journal.sqlite';Journal.enroll(p,**SCOPE)
 def prepare(_):return Journal(p,**SCOPE).prepare('session','call',args())
 with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(prepare,range(12)))
 assert all(x==results[0] for x in results)
 with sqlite3.connect(p) as c:assert c.execute('SELECT COUNT(*) FROM calls').fetchone()[0]==1


from test_worker_boundary import instance

def test_cached_receipt_requires_live_operation(instance,tmp_path):
 db,_,sock,rev=instance
 with sqlite3.connect(db) as c:epoch=c.execute('SELECT epoch FROM projects').fetchone()[0]
 scope={**SCOPE,'epoch':epoch};p=tmp_path/'host.sqlite';Journal.enroll(p,**scope)
 j=Journal(p,**scope);j.execute(sock,'session','call',args(rev))
 with sqlite3.connect(db) as c:c.execute('DELETE FROM operations')
 with pytest.raises(ValueError):j.execute(sock,'session','call',args(rev))
 with sqlite3.connect(p) as c:assert c.execute('SELECT COUNT(*) FROM calls').fetchone()[0]==1

def test_concurrent_execute_same_call(instance,tmp_path):
 from concurrent.futures import ThreadPoolExecutor
 db,_,sock,rev=instance
 with sqlite3.connect(db) as c:epoch=c.execute('SELECT epoch FROM projects').fetchone()[0]
 scope={**SCOPE,'epoch':epoch};p=tmp_path/'concurrent.sqlite';Journal.enroll(p,**scope)
 def execute(_):return Journal(p,**scope).execute(sock,'session','call',args(rev))
 with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(execute,range(4)))
 assert all(x==results[0] for x in results)
 with sqlite3.connect(db) as c:assert c.execute('SELECT COUNT(*) FROM proposals').fetchone()[0]==1

def test_stale_journal_lost_row_retains_remote_identity(instance,tmp_path):
 db,_,sock,rev=instance
 with sqlite3.connect(db) as c:epoch=c.execute('SELECT epoch FROM projects').fetchone()[0]
 scope={**SCOPE,'epoch':epoch};p=tmp_path/'rollback.sqlite';Journal.enroll(p,**scope)
 j=Journal(p,**scope);first=j.execute(sock,'session','call',args(rev))
 # Simulate restoring journal snapshot from before this row existed.
 with sqlite3.connect(p) as c:c.execute('DELETE FROM calls')
 assert Journal(p,**scope).execute(sock,'session','call',args(rev))==first
 with sqlite3.connect(p) as c:c.execute('DELETE FROM calls')
 with pytest.raises(ValueError):Journal(p,**scope).execute(sock,'session','call',{**args(rev),'markdown':'changed after journal rollback'})
 with sqlite3.connect(db) as c:assert c.execute('SELECT COUNT(*) FROM proposals').fetchone()[0]==1
