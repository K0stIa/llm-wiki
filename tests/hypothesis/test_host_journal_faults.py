"""Real SQLite faults, synthetic data only. No mocked success/error responses."""
import json,os,select,sqlite3,subprocess,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/mcp'));sys.path.insert(0,str(ROOT/'src/authority'))
from host_journal import Journal
from authority import connect_knowledge,ChangeKind,DecisionKind
from test_host_journal import args,SCOPE
from test_worker_boundary import instance

@pytest.mark.parametrize('fault',['busy','full'])
def test_journal_prepare_fault_has_no_row_or_receipt(tmp_path,fault):
 p=tmp_path/'journal.sqlite';Journal.enroll(p,**SCOPE);j=Journal(p,**SCOPE)
 original=j._connect
 def bounded():
  c=original();c.execute('PRAGMA busy_timeout=25')
  if fault=='full':c.execute('PRAGMA max_page_count='+str(c.execute('PRAGMA page_count').fetchone()[0]))
  return c
 j._connect=bounded
 lock=sqlite3.connect(p)
 try:
  if fault=='busy':lock.execute('BEGIN IMMEDIATE')
  with pytest.raises(sqlite3.OperationalError) as error:j.prepare('session','call',{**args(),'markdown':'x'*65536})
  assert error.value.sqlite_errorcode=={'busy':sqlite3.SQLITE_BUSY,'full':sqlite3.SQLITE_FULL}[fault]
 finally:lock.rollback();lock.close()
 with sqlite3.connect(p) as c:
  assert c.execute('SELECT COUNT(*) FROM calls').fetchone()[0]==0
  assert c.execute('PRAGMA integrity_check').fetchone()==('ok',)
 # Recovery retries the same identity after removing only synthetic fault.
 j._connect=original;assert j.prepare('session','call',args())['args']['key']

@pytest.mark.parametrize('fault',['busy','full'])
def test_authority_proposal_fault_preserves_head_and_accepted_source(tmp_path,fault):
 p=tmp_path/'authority.sqlite';s=connect_knowledge(str(p),'alpha')
 page=s.create_page('alpha','page','Title','Original','owner')
 source=s.capture_source('alpha','Accepted','Accepted immutable evidence','synthetic://source')
 c=s.connect('alpha');c.execute('PRAGMA busy_timeout=25')
 if fault=='full':c.execute('PRAGMA max_page_count='+str(c.execute('PRAGMA page_count').fetchone()[0]))
 lock=sqlite3.connect(p)
 try:
  if fault=='busy':lock.execute('BEGIN IMMEDIATE')
  with pytest.raises(sqlite3.OperationalError) as error:s.propose('alpha','page',page.revision,ChangeKind.REPLACE,'Title','x'*65536,'worker',[],key='stable')
  assert error.value.sqlite_errorcode=={'busy':sqlite3.SQLITE_BUSY,'full':sqlite3.SQLITE_FULL}[fault]
 finally:lock.rollback();lock.close()
 assert c.execute('SELECT COUNT(*) FROM proposals').fetchone()[0]==0
 assert c.execute('SELECT COUNT(*) FROM operations').fetchone()[0]==0
 assert c.execute('SELECT revision FROM page_heads').fetchone()[0]==page.revision
 assert c.execute('SELECT COUNT(*) FROM page_revisions').fetchone()[0]==1
 assert c.execute('SELECT text FROM evidence_revisions WHERE revision=?',(source,)).fetchone()[0]=='Accepted immutable evidence'
 assert c.execute('PRAGMA integrity_check').fetchone()==('ok',)
 s.disconnect()


@pytest.mark.parametrize('fault',['busy','full'])
def test_receipt_fault_keeps_valid_pending_and_replays(instance,tmp_path,fault):
 db,_,sock,rev=instance
 with sqlite3.connect(db) as c:epoch=c.execute('SELECT epoch FROM projects').fetchone()[0]
 p=tmp_path/'journal.sqlite';scope={**SCOPE,'epoch':epoch};Journal.enroll(p,**scope);j=Journal(p,**scope)
 j.prepare('session','call',args(rev))
 with sqlite3.connect(p) as c:
  c.execute('CREATE TABLE filler(data BLOB)')
  c.execute('CREATE TRIGGER force_full BEFORE UPDATE OF receipt ON calls BEGIN INSERT INTO filler VALUES(randomblob(65536)); END')
 original=j._connect
 def limited():
  c=original();c.execute('PRAGMA busy_timeout=25')
  if fault=='full':c.execute('PRAGMA max_page_count='+str(c.execute('PRAGMA page_count').fetchone()[0]))
  return c
 lock=sqlite3.connect(p);send=j.send
 def locked_send(endpoint,request):
  result=send(endpoint,request)
  if fault=='busy' and request['tool']=='wiki_host_propose':lock.execute('BEGIN IMMEDIATE')
  return result
 j.send=locked_send
 j._connect=limited
 try:
  with pytest.raises(sqlite3.OperationalError) as error:j.execute(sock,'session','call',args(rev))
  assert error.value.sqlite_errorcode=={'busy':sqlite3.SQLITE_BUSY,'full':sqlite3.SQLITE_FULL}[fault]
 finally:lock.rollback();lock.close();j.send=send
 with sqlite3.connect(p) as c:
  assert c.execute('SELECT receipt FROM calls').fetchone()==(None,)
  assert c.execute('SELECT COUNT(*) FROM filler').fetchone()[0]==0
  c.execute('DROP TRIGGER force_full')
 with sqlite3.connect(db) as c:
  assert c.execute('SELECT COUNT(*) FROM proposals').fetchone()[0]==1
  assert c.execute('SELECT state FROM proposals').fetchone()[0]=='pending'
  assert c.execute('SELECT revision FROM page_heads').fetchone()[0]==rev
 j._connect=original;assert j.execute(sock,'session','call',args(rev))['result']['kind']=='pending'
 with sqlite3.connect(db) as c:assert c.execute('SELECT COUNT(*) FROM proposals').fetchone()[0]==1


def test_kill_during_publication_rolls_back_half_revision(tmp_path):
 p=tmp_path/'authority.sqlite';s=connect_knowledge(str(p),'alpha')
 page=s.create_page('alpha','page','Title','Original','owner')
 source=s.capture_source('alpha','Accepted','Evidence survives cancellation','synthetic://source')
 s.propose('alpha','page',page.revision,ChangeKind.REPLACE,'New','Replacement','worker',[],key='stable');s.disconnect()
 code='''import sys,time
from authority import connect_knowledge,DecisionKind
s=connect_knowledge(sys.argv[1],'alpha');c=s.connect('alpha')
def barrier(sql):
 if sql.lstrip().upper().startswith('UPDATE PAGE_HEADS'):
  print('IN_TRANSACTION',flush=True);time.sleep(60)
c.set_trace_callback(barrier)
s.decide('alpha','stable',DecisionKind.PUBLISH)
print('SUCCESS',flush=True)
'''
 child=subprocess.Popen([sys.executable,'-c',code,str(p)],env={**os.environ,'PYTHONPATH':str(ROOT/'src/authority')},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 try:
  assert select.select([child.stdout],[],[],5)[0]
  assert child.stdout.readline().strip()=='IN_TRANSACTION'
  child.kill();child.wait(timeout=5)
  assert 'SUCCESS' not in child.stdout.read()
 finally:
  if child.poll() is None:child.kill();child.wait()
 with sqlite3.connect(p) as c:
  assert c.execute('PRAGMA integrity_check').fetchone()==('ok',)
  assert c.execute('SELECT revision FROM page_heads').fetchone()[0]==page.revision
  assert c.execute('SELECT COUNT(*) FROM page_revisions').fetchone()[0]==1
  assert c.execute('SELECT state FROM page_revisions').fetchone()[0]=='active'
  assert c.execute('SELECT state FROM proposals').fetchone()[0]=='pending'
  assert c.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]==0
  assert c.execute('SELECT text FROM evidence_revisions WHERE revision=?',(source,)).fetchone()[0]=='Evidence survives cancellation'
 s=connect_knowledge(str(p),'alpha');assert s.decide('alpha','stable',DecisionKind.PUBLISH).kind=='committed';s.disconnect()
