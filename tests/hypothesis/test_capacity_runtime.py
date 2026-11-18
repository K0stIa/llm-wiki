"""Bounded backlog admission, real persisted authority and public service calls."""
import concurrent.futures
import sqlite3
from test_bridge_recovery_runtime import node, call, ROOT
from src.authority.authority import connect_knowledge, ChangeKind


def seed(db, count):
    s=connect_knowledge(db,'a'); page=s.create_page('a','p','Title','Original body','owner')
    for i in range(count):
        s.propose('a','p',page.revision,ChangeKind.REPLACE,'Title',f'Body {i}','worker',[],key=f'k{i}')
    s.disconnect(); return page.revision


def service(db, principal, name, project='a', **args):
    return {'tool':'service','binding':[db,project,principal],'name':name,'args':args}


def proposal(db,rev,key):
    return service(db,'worker','wiki_propose',page='p',baseRevision=rev,changeKind='replace',title='Title',markdown=key,key=key)


def test_backlog_cap_and_metadata_rejection(tmp_path):
    db=str(tmp_path/'capacity.sqlite'); rev=seed(db,100)
    with sqlite3.connect(db) as c:
        c.execute("UPDATE proposals SET state='blocked'")
        before={t:c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ['proposals','operations','evidence_revisions']}
        seq=c.execute("SELECT sequence FROM projects WHERE id='a'").fetchone()[0]
    denied=node(proposal(db,rev,'overflow'))[0]
    assert denied['kind']=='error' and 'capacity' in denied['message'].lower(),denied
    for principal,project in [('worker','a'),('curator','b')]:
        assert node(service(db,principal,'wiki_curator_decide',project=project,proposalKey='k0',decision='reject',reason='metadata timeout'))[0]['kind']=='error'
    rejected=node(service(db,'curator','wiki_curator_decide',proposalKey='k0',decision='reject',reason='metadata timeout'))[0]
    assert rejected['kind']=='rejected',rejected
    assert node(service(db,'curator','wiki_curator_decide',proposalKey='k0',decision='reject',reason='metadata timeout'))[0]==rejected
    with sqlite3.connect(db) as c:
        assert before=={t:c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in before}
        assert c.execute("SELECT sequence FROM projects WHERE id='a'").fetchone()[0]==seq
        assert c.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]==1
    assert node(proposal(db,rev,'now-admitted'))[0]['kind']=='pending'
    assert node(proposal(db,rev,'again-full'))[0]['kind']=='error'


def test_concurrent_public_admission_never_exceeds_cap(tmp_path):
    db=str(tmp_path/'concurrent.sqlite'); rev=seed(db,99)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(lambda i:node(proposal(db,rev,f'race-{i}'))[0],range(8)))
    assert sum(r['kind']=='pending' for r in results)==1,results
    assert sum(r['kind']=='error' for r in results)==7,results
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT COUNT(*) FROM proposals WHERE state IN ('pending','blocked')").fetchone()[0]==100
        assert c.execute('SELECT COUNT(*) FROM operations').fetchone()[0]==100


def test_metadata_sweep_records_durable_decisions(tmp_path):
    from src.authority.authority import Curator
    db=str(tmp_path/'sweep.sqlite');seed(db,3)
    s=connect_knowledge(db,'a');c=s.connect('a')
    with c:c.execute("UPDATE proposals SET state='blocked'")
    assert Curator(s).metadata_sweep('a')==3
    s.disconnect();s=connect_knowledge(db,'a');c=s.connect('a')
    assert c.execute("SELECT COUNT(*) FROM decisions WHERE decision_kind='reject'").fetchone()[0]==3
    assert c.execute('SELECT COUNT(*) FROM proposals').fetchone()[0]==3
    assert c.execute('SELECT COUNT(*) FROM operations').fetchone()[0]==3
    assert Curator(s).metadata_sweep('a')==0
    s.disconnect()


def test_public_service_retains_explicit_key_and_rejects_changed_payload(tmp_path):
    db=str(tmp_path/'keys.sqlite');rev=seed(db,0)
    request=proposal(db,rev,'caller-key')
    first=node(request)[0]
    assert first['key']=='caller-key'
    assert node(request)[0]==first
    request['args']['markdown']='different payload'
    assert node(request)[0]['kind']=='error'


def test_metadata_rejection_never_authorizes_publication(tmp_path):
    db=str(tmp_path/'publication.sqlite');rev=seed(db,1)
    assert node(service(db,'curator','wiki_curator_decide',proposalKey='k0',decision='publish'))[0]['kind']=='error'
    with sqlite3.connect(db) as c:c.execute("UPDATE proposals SET state='blocked'")
    pending=node(service(db,'curator','wiki_curator_pending',limit=1))[0]['items'][0]
    assert node(service(db,'curator','wiki_curator_decide',proposalKey='k0',decision='publish',digest=pending['reviewDigest']))[0]['kind']=='error'
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT revision FROM page_heads').fetchone()[0]==rev
        assert c.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]==0


def test_terminal_publication_and_conflict_replay_are_durable(tmp_path):
    db=str(tmp_path/'terminal.sqlite');seed(db,2)
    items=node(service(db,'curator','wiki_curator_pending',limit=10))[0]['items']
    digests={i['body']:i['reviewDigest'] for i in items}
    first=service(db,'curator','wiki_curator_decide',proposalKey='k0',decision='publish',digest=digests['Body 0'])
    loser=service(db,'curator','wiki_curator_decide',proposalKey='k1',decision='publish',digest=digests['Body 1'])
    committed=node(first)[0];assert committed['kind']=='committed'
    conflict=node(loser)[0];assert conflict['kind']=='conflict'
    with sqlite3.connect(db) as c:
        counts={t:c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ['page_revisions','decisions','outbox']}
        assert c.execute("SELECT COUNT(*) FROM proposals WHERE state='decided'").fetchone()[0]==2
    assert node(first)[0]==committed
    assert node(loser)[0]==conflict
    assert node(service(db,'curator','wiki_curator_decide',proposalKey='k0',decision='reject',reason='contradiction'))[0]['kind']=='error'
    assert node(service(db,'curator','wiki_curator_decide',proposalKey='k1',decision='reject',reason='contradiction'))[0]['kind']=='error'
    with sqlite3.connect(db) as c:
        assert counts=={t:c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in counts}
        c.execute("UPDATE decisions SET decision_json='{}' WHERE proposal_id=(SELECT proposal_id FROM proposal_keys WHERE key='k0')")
    assert node(first)[0]['kind']=='error' # legacy missing receipt cannot be fabricated
