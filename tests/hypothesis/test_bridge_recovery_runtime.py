"""Real TypeScript -> Python and SQLite backup/restore, exclusively temporary data."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.authority.authority import connect_knowledge, ChangeKind, DecisionKind


def node(*calls, env=None):
    run = subprocess.run(['node', str(ROOT/'node_modules/tsx/dist/cli.mjs'),
                          str(ROOT/'tests/runtime/bridge-client.mjs')],
                         input=json.dumps({'calls': list(calls)}), text=True,
                         capture_output=True, cwd=ROOT, env=env, timeout=45)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    assert 'exception' not in result, result
    return result['results']


def call(tool, *args):
    return {'tool': tool, 'args': list(args)}


def test_actual_bridge_roundtrip_and_scoped_failure(tmp_path):
    db=str(tmp_path/'db with spaces $dollar; quote\'.sqlite')
    body='Full body beyond fifty characters. Привіт світ. "quotes"; $(touch NOT_ALLOWED)\nDistinct tail.'
    connected, created, read=node(call('connect',db,'a'),call('createPage',db,'a','p','Title',body,'worker'),call('page',db,'a','p'))
    assert connected['kind']=='connected'
    assert created['kind']=='page' and created['markdown']==body==read['markdown']
    assert read['hash']=='h:'+hashlib.sha256(body.encode()).hexdigest()
    evidence=connect_knowledge(db,'a');sources=[]
    for i in range(3):
        text=f'captured evidence {i}'
        revision=evidence.capture_source('a',f'Evidence {i}',text,f'synthetic:{i}')
        sources.append({'kind':'source','source':revision,'revision':revision,'start':1,'end':1,'hash':'h:'+hashlib.sha256(text.encode()).hexdigest()})
    receipt=node(call('propose',db,'a','p',read['revision'],'replace','New',body+' NEW','worker',sources))[0]
    assert receipt['kind']=='pending'
    assert node(call('propose',db,'a','p',read['revision'],'replace','New',body+' NEW','worker',sources,receipt['key']))[0]==receipt
    assert node(call('propose',db,'a','p',read['revision'],'replace','New','changed request','worker',sources,receipt['key']))[0]['kind']=='error'
    assert node(call('propose',db,'a','p',read['revision'],'replace','New',body+' NEW','other',sources,receipt['key']))[0]['kind']=='error'
    pending=node(call('pendingProposals',db,'a'))[0]
    assert pending['items'][0]['body']==body+' NEW'
    assert pending['items'][0]['sources']==sources
    reviewed=pending['items'][0]['reviewDigest']
    denied=node(call('decide',db,'a',receipt['key'],'publish','wrong'))[0]
    assert denied['kind']=='error'
    outcome=node(call('decide',db,'a',receipt['key'],'publish',reviewed))[0]
    assert outcome['kind']=='committed'
    assert node(call('propose',db,'a','p',read['revision'],'replace','New',body+' NEW','worker',sources,receipt['key']))[0]==receipt
    assert node(call('page',db,'a','p'))[0]['markdown']==body+' NEW'
    assert node(call('page',db,'a','p',read['revision']))[0]['markdown']==body
    op=node(call('operation',db,'a',receipt['key'],'worker'))[0]
    assert op['kind']=='operation' and op['status']=='committed'
    service_denied=node({'tool':'service','binding':[db,'a','worker'],'name':'wiki_curator_decide','args':{'proposalKey':receipt['key'],'digest':reviewed,'decision':'publish'}})[0]
    assert service_denied['kind']=='error' and service_denied['error']=='unauthorized'
    assert node(call('operation',db,'a',receipt['key'],'other'))[0]['kind']=='unknown'
    assert node(call('page',db,'b','p',read['revision']))[0]['kind']=='error'
    assert node(call('decide',db,'b',receipt['key'],'publish',reviewed))[0]['kind']=='error'
    assert node(call('pendingProposals',db,'a',20,'unsupported'))[0]['kind']=='error'
    assert node(call('verifyBoundary',str(tmp_path/'boundary.sqlite')))==[True]
    assert node(call('verifyBoundary',str(tmp_path)))==[False]
    assert not (ROOT/'NOT_ALLOWED').exists()


def test_bound_services_preserve_errors_and_curator_identity(tmp_path):
    db=str(tmp_path/'services.sqlite')
    a,b=node(call('createPage',db,'a','same','A','alpha body','owner'),call('createPage',db,'b','same','B','beta body','owner'))
    def service(bound_project,principal,name,**args):
        return node({'tool':'service','binding':[db,bound_project,principal],'name':name,'args':args})[0]
    assert service('a','worker','wiki_page',page='same',project='b')['markdown']=='alpha body'
    assert service('b','worker','wiki_page',page='same')['markdown']=='beta body'
    assert service('a','worker','wiki_page',page='same',revision=b['revision'])['kind']=='error'
    assert service('a','worker','wiki_curator_pending')['error']=='unauthorized'
    assert service('a','curator','wiki_propose',page='same',baseRevision=a['revision'],changeKind='replace',title='X',markdown='X')['kind']=='error'
    proposed=service('a','worker','wiki_propose',page='same',baseRevision=a['revision'],changeKind='replace',title='Changed',markdown='service change')
    pending=service('a','curator','wiki_curator_pending')['items'][0]
    outcome=service('a','curator','wiki_curator_decide',proposalKey=proposed['key'],digest=pending['reviewDigest'],decision='publish')
    assert outcome['kind']=='committed'
    assert service('a','worker','wiki_page',page='same')['markdown']=='service change'
    fixture=connect_knowledge(db,'a')
    own=fixture.propose('a','same',fixture.page('a','same').revision,ChangeKind.REPLACE,'Own','old curator-authored fixture','curator',[])
    review=service('a','curator','wiki_curator_pending')['items'][0]
    assert service('a','curator','wiki_curator_decide',proposalKey=own.key,digest=review['reviewDigest'],decision='publish')['kind']=='error'


def test_pending_cursor_is_bounded_scoped_and_has_a_scan_cutoff(tmp_path):
    db=str(tmp_path/'pending.sqlite');head=node(call('createPage',db,'a','p','T','base','owner'))[0]
    for i in range(3):
        assert node(call('propose',db,'a','p',head['revision'],'replace',f'T{i}',f'body{i}','worker',[]))[0]['kind']=='pending'
    first=node(call('pendingProposals',db,'a',1))[0]
    assert len(first['items'])==1 and first['next']
    node(call('propose',db,'a','p',head['revision'],'replace','Late','late body','worker',[]))
    second=node(call('pendingProposals',db,'a',1,first['next']))[0]
    third=node(call('pendingProposals',db,'a',1,second['next']))[0]
    assert len({first['items'][0]['id'],second['items'][0]['id'],third['items'][0]['id']})==3 and third['next'] is None
    assert len(node(call('pendingProposals',db,'a',100))[0]['items'])==4
    assert node(call('pendingProposals',db,'b',1,first['next']))[0]['kind']=='error'
    receipt=node(call('backup',db,'a',str(tmp_path/'backups')))[0]
    restored=node(call('restore',receipt['path'],str(tmp_path/'restored')))[0]
    assert node(call('pendingProposals',restored['path'],'a',1,first['next']))[0]['kind']=='error'


def test_missing_database_and_temp_cleanup(tmp_path):
    env=os.environ.copy(); scratch=tmp_path/'scratch';scratch.mkdir();env['TMPDIR']=str(scratch)
    result=node(call('connect',str(tmp_path),'a'),call('page',str(tmp_path),'a','p'),env=env)
    assert all(x['kind']=='error' for x in result)
    assert not list(scratch.glob('wiki-bridge-*'))
    assert not list(scratch.glob('bridge-*'))


@pytest.mark.parametrize('reply', ['exit 7','printf null','printf "{}"','printf not-json'])
def test_subprocess_faults_never_become_success(tmp_path,reply):
    bin_dir=tmp_path/'bin';bin_dir.mkdir()
    python=bin_dir/'python3';python.write_text('#!/bin/sh\n'+reply+'\n');python.chmod(0o700)
    env=os.environ.copy();env['PATH']=str(bin_dir)+os.pathsep+env['PATH'];env['TMPDIR']=str(tmp_path)
    result=node(call('connect',str(tmp_path/'db'),'a'),call('createPage',str(tmp_path/'db'),'a','p','T','B','worker'),call('verifyBoundary',str(tmp_path/'db')),env=env)
    assert result[0]['kind']=='error' and result[1]['kind']=='error' and result[2] is False
    if reply=='exit 7':assert '7' in result[0]['message']
    assert not list(tmp_path.glob('wiki-bridge-*'))


def seeded(tmp_path):
    db=tmp_path/'source.sqlite';s=connect_knowledge(db,'a')
    first=s.create_page('a','p','Title','first retained full body '+'x'*90,'owner')
    proposal=s.propose('a','p',first.revision,ChangeKind.REPLACE,'Next','second retained body '+'y'*90,'worker',[])
    s.decide('a',proposal.key,DecisionKind.PUBLISH)
    pending=s.propose('a','p',s.page('a','p').revision,ChangeKind.REPLACE,'Pending','pending full body '+'z'*90,'worker',[],key='pending-key')
    source=s.capture_source('a','Evidence','exact retained source text','synthetic:source')
    other=connect_knowledge(db,'b');other.create_page('b','p','Other','other project retained','owner')
    return db,s,first,pending,source


def test_backup_restore_epochs_exact_history_and_review(tmp_path):
    db,s,first,pending,source=seeded(tmp_path)
    before=node(call('pendingProposals',str(db),'a'))[0]['items'][0]
    receipt=node(call('backup',str(db),'a',str(tmp_path/'backups')))[0]
    assert receipt['kind']=='backup'
    assert receipt['hash']=='h:'+hashlib.sha256(Path(receipt['path']).read_bytes()).hexdigest()
    manifest=json.loads(Path(receipt['manifestPath']).read_text());assert manifest['version']==1
    backup_sequence=receipt['sequence'];backup_epoch=receipt['epoch']
    lost=s.create_page('a','lost','Lost','post-backup barrier','owner')
    lost_source=s.capture_source('a','Lost source','lost evidence','synthetic:lost')
    lost_proposal=s.propose('a','p',s.page('a','p').revision,ChangeKind.REPLACE,'Lost proposal','lost proposal body','worker',[])
    restored=node(call('restore',receipt['path'],str(tmp_path/'restored')))[0]
    assert restored['success'] is True and restored['newEpoch']!=backup_epoch
    assert restored['oldEpoch']==backup_epoch and restored['restoredSequence']==backup_sequence
    assert s._get_epoch('a')==backup_epoch
    assert lost.revision.startswith('rev-'+backup_epoch+'-')
    assert restored['retainedRevisions']==manifest['revisionCount'] and restored['lostRevisions'] is None
    target=Path(restored['path']);new=connect_knowledge(target,'a');conn=new.connect('a')
    assert new.page('a','p',first.revision).markdown==first.markdown
    assert conn.execute('SELECT text FROM evidence_revisions WHERE revision=?',(source,)).fetchone()[0]=='exact retained source text'
    assert conn.execute('SELECT 1 FROM evidence_revisions WHERE revision=?',(lost_source,)).fetchone() is None
    assert conn.execute('SELECT 1 FROM proposals WHERE proposal_id=?',(lost_proposal.proposal,)).fetchone() is None
    assert node(call('operation',str(target),'a',lost_proposal.key,'worker'))[0]['kind']=='unknown'
    reissued=node(call('propose',str(target),'a','p',new.page('a','p').revision,'replace','Lost proposal','lost proposal body','worker',[]))[0]
    assert reissued['key']!=lost_proposal.key and reissued['proposal']!=lost_proposal.proposal
    assert reissued['key'].startswith('key:'+restored['newEpoch']+':')
    fresh_source=new.capture_source('a','Lost source','lost evidence','synthetic:lost')
    assert fresh_source!=lost_source and fresh_source.startswith('src-'+restored['newEpoch']+'-')
    assert node(call('page',str(target),'a','lost',lost.revision))[0]['kind']=='error'
    assert conn.execute('SELECT COUNT(*) FROM retrieval_generations').fetchone()[0]==0
    assert conn.execute("SELECT COUNT(*) FROM outbox WHERE kind='index' AND status='pending'").fetchone()[0]==2
    epochs=dict(conn.execute('SELECT id,epoch FROM projects'));assert all(p['newEpoch']==epochs[p['project']] and p['newEpoch']!=p['oldEpoch'] for p in restored['projects'])
    stale=node(call('decide',str(target),'a',pending.key,'publish',before['reviewDigest']))[0]
    assert stale['kind']=='error'
    replay=node(call('propose',str(target),'a','p',new.page('a','p').revision,'replace','Pending',before['body'],'worker',[],'pending-key'))[0]
    assert replay['kind']=='error'
    after=node(call('pendingProposals',str(target),'a'))[0]['items'][0]
    assert after['body']==before['body'] and after['digest']==before['digest'] and after['reviewDigest']!=before['reviewDigest']
    assert node(call('decide',str(target),'a',pending.key,'publish',after['reviewDigest']))[0]['kind']=='committed'
    new.create_page('a','lost','Recreated','different replacement','owner')
    assert new.page('a','lost').revision!=lost.revision
    assert new.page('a','lost').revision.startswith('rev-'+restored['newEpoch']+'-')
    assert node(call('page',str(target),'a','lost',lost.revision))[0]['kind']=='error'


@pytest.mark.parametrize('fault', ['missing','corrupt','sqlite','manifest','occupied'])
def test_restore_failures_do_not_replace_existing_data(tmp_path,fault):
    db,s,first,pending,source=seeded(tmp_path)
    receipt=node(call('backup',str(db),'a',str(tmp_path/'backups')))[0]
    backup=Path(receipt['path']);target=tmp_path/'destination'
    if fault=='missing': backup.unlink()
    if fault=='corrupt':
        with backup.open('ab') as out:out.write(b'corrupt')
    if fault=='sqlite':
        backup.write_bytes(b'not a SQLite database')
        p=Path(receipt['manifestPath']);m=json.loads(p.read_text());m['hash']='h:'+hashlib.sha256(backup.read_bytes()).hexdigest();m['sizeBytes']=backup.stat().st_size;p.write_text(json.dumps(m))
    if fault=='manifest':
        p=Path(receipt['manifestPath']);m=json.loads(p.read_text());m['projects'][0]['sequence']+=1;p.write_text(json.dumps(m))
    if fault=='occupied': target.mkdir();(target/'keep').write_bytes(b'accepted existing data')
    result=node(call('restore',str(backup),str(target)))[0]
    assert result['success'] is False and result['error']
    if fault=='sqlite':assert 'DatabaseError' in result['error']
    if fault=='occupied':assert (target/'keep').read_bytes()==b'accepted existing data'
    else:assert not target.exists()
    assert s.page('a','p',first.revision).markdown==first.markdown
    assert not list(tmp_path.glob('.wiki-restore-*'))


def test_online_backup_includes_committed_wal_without_checkpoint(tmp_path):
    db=tmp_path/'wal.sqlite';s=connect_knowledge(db,'a');conn=s.connect('a');conn.execute('PRAGMA wal_autocheckpoint=0')
    page=s.create_page('a','wal','WAL','committed only in WAL','owner')
    assert Path(str(db)+'-wal').stat().st_size>0
    stop=threading.Event();ready=threading.Event();errors=[]
    def writer():
        w=connect_knowledge(db,'a')
        try:
            i=0
            while not stop.is_set():
                w.create_page('a',f'concurrent-{i}','Concurrent',f'committed {i}','owner');i+=1;ready.set();time.sleep(.005)
        except Exception as error:errors.append(error)
        finally:w.disconnect()
    thread=threading.Thread(target=writer);thread.start();assert ready.wait(5)
    try:
        receipt=node(call('backup',str(db),'a',str(tmp_path/'backups')))[0]
        assert thread.is_alive()
    finally:stop.set();thread.join(10)
    assert not thread.is_alive() and not errors
    restored=node(call('restore',receipt['path'],str(tmp_path/'restored')))[0]
    assert restored['success'] is True
    assert node(call('page',restored['path'],'a','wal'))[0]['markdown']==page.markdown
    with sqlite3.connect(restored['path']) as recovered:
        count=recovered.execute('SELECT COUNT(*) FROM page_heads').fetchone()[0]
        assert count==receipt['sequence'] and count>=2
        assert recovered.execute('PRAGMA integrity_check').fetchone()[0]=='ok'


@pytest.mark.tier_b
def test_restore_bootstrap_and_old_barrier_never_becomes_current(tmp_path):
    model=os.environ.get('WIKI_TEST_CACHED_MODEL')
    assert model and Path(model).is_file(), 'explicit approved cached model required, no downloads'
    db,s,first,pending,source=seeded(tmp_path)
    binding={'database':str(db),'project':'a','indexRoot':str(tmp_path/'indexes'),'model':model}
    def retrieve(action, **extra):
        run=subprocess.run(['node',str(ROOT/'node_modules/tsx/dist/cli.mjs'),str(ROOT/'tests/runtime/retrieval-client.mjs')],
                           input=json.dumps({'action':action,'binding':binding,**extra})+'\n',
                           text=True,capture_output=True,cwd=ROOT,timeout=45)
        assert run.returncode==0,run.stderr
        result=json.loads(run.stdout);assert 'error' not in result,result
        return result['value']
    generation=retrieve('build')
    receipt=node(call('backup',str(db),'a',str(tmp_path/'backups')))[0]
    lost=s.create_page('a','lost','Lost','lost after backup','owner')
    old_barrier=f"a:{receipt['epoch']}:{receipt['sequence']+1}"
    result=node(call('restore',receipt['path'],str(tmp_path/'restored')))[0]
    assert result['success'] is True
    binding['database']=result['path']
    assert retrieve('recall',input={'query':'retained','coverage':'require-hybrid-current'})['kind']=='not-ready'
    fresh_generation=retrieve('build')
    assert fresh_generation['target']['epoch']!=generation['target']['epoch']
    # No authority writes between restore and this successful bootstrap query.
    assert retrieve('recall',input={'query':'retained','coverage':'require-hybrid-current'})['coverage']=='hybrid-current'
    new=connect_knowledge(result['path'],'a');replacement=new.create_page('a','lost','Recreated','new body','owner')
    assert replacement.revision!=lost.revision
    assert new.connect('a').execute("SELECT sequence FROM projects WHERE id='a'").fetchone()[0]==receipt['sequence']+1
    assert retrieve('recall',input={'query':'retained','atLeast':old_barrier})['reason']=='stale-epoch'
    assert node(call('page',result['path'],'a','lost',lost.revision))[0]['kind']=='error'


def test_backup_failure_is_not_a_receipt(tmp_path):
    db,s,first,pending,source=seeded(tmp_path)
    occupied=tmp_path/'not-a-directory';occupied.write_bytes(b'keep')
    result=node(call('backup',str(db),'a',str(occupied)))[0]
    assert result['kind']=='error' and 'path' not in result
    assert occupied.read_bytes()==b'keep'
