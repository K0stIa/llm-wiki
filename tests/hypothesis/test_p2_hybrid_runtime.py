"""Real cached QMD 2.8.3, authority FTS5 and SDK. No network/model mocks."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.tier_b

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.authority.authority import connect_knowledge, ChangeKind, DecisionKind, AuthorityError
from src.authority import retrieval


class Driver:
    def __init__(self):
        self.proc = subprocess.Popen(['node', 'node_modules/tsx/dist/cli.mjs', 'tests/runtime/retrieval-client.mjs'],
                                     cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True)

    def request(self, action, **kwargs):
        self.proc.stdin.write(json.dumps({'action': action, **kwargs}) + '\n')
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        assert line, f'adapter process ended: {self.proc.poll()}'
        return json.loads(line)

    def call(self, action, **kwargs):
        result = self.request(action, **kwargs)
        assert result['ok'], result
        return result['value']

    def close(self):
        self.proc.stdin.close()
        assert self.proc.wait(timeout=30) == 0


@pytest.fixture
def system(tmp_path):
    model = os.environ.get('WIKI_TEST_CACHED_MODEL')
    assert model and Path(model).is_file(), 'Explicit existing approved cached model required; downloads are forbidden'
    store = connect_knowledge(str(tmp_path/'authority.db'), 'a')
    page = store.create_page('a','engine','Engine','The amber engine uses a sapphire coolant pump.','owner')
    other = connect_knowledge(str(tmp_path/'authority.db'), 'b')
    other.create_page('b','forbidden','Forbidden','The forbidden thermal circulation device.','owner')
    binding = dict(database=str(tmp_path/'authority.db'),project='a',indexRoot=str(tmp_path/'indexes'),model=model)
    driver = Driver()
    yield store, page, binding, driver
    driver.close()


def publish(store, page, body, kind=ChangeKind.REPLACE):
    receipt = store.propose('a',page.page,page.revision,kind,'Updated',body,'worker',[])
    outcome = store.decide('a',receipt.key,DecisionKind.PUBLISH)
    assert outcome.kind == 'committed'
    return store.page('a',page.page)


def tree(directory):
    return {str(p.relative_to(directory)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(directory).rglob('*') if p.is_file()}


def test_real_vector_rrf_and_mcp(system):
    store, page, binding, d = system
    manifest = d.call('build',binding=binding)
    assert manifest['qmdVersion'] == '2.8.3'
    # Every QMD document is titled with its authority page title, never with the (revision-derived) file name:
    # QMD embeds the title, so a key-derived title made vectors noisy and load-dependent.
    import sqlite3
    index = Path(binding['indexRoot'])/hashlib.sha256(b'a').hexdigest()/manifest['generation']/'index.sqlite'
    titles = {t for (t,) in sqlite3.connect(f'file:{index}?mode=ro&immutable=1',uri=True).execute('SELECT title FROM documents')}
    assert titles == {'Engine'}
    assert manifest['target']['sequence'] == 1
    state = store.connect('a').execute('SELECT sequence FROM retrieval_generations WHERE project=?',('a',)).fetchone()
    assert state[0] == 1
    query = 'thermal circulation device'
    assert d.call('snapshot',binding=binding,query=query)['lexical'] == []
    answer = d.call('recall',binding=binding,input=dict(query=query,coverage='require-hybrid-current'))
    assert answer['coverage'] == 'hybrid-current'
    assert answer['evidence']['passages'][0]['page'] == 'engine'  # real semantic-only candidate
    assert all(p.get('page') != 'forbidden' for p in answer['evidence']['passages'])
    hit = answer['evidence']['passages'][0]
    assert hit['revision'] == page.revision and hit['hash'] == page.hash
    assert hit['citation']['revision'] == hit['revision'] and hit['citation']['start'] == hit['start']
    assert hit['snapshot'] == answer['snapshot']
    assert hit['text'] == '\n'.join(page.markdown.split('\n')[hit['start']-1:hit['end']])
    # One branch ranks x first, the other ranks y first. Rank fusion ignores raw scores.
    assert d.call('fuse',lexical=['x','x','y'],vector=['y','z']) == ['y','x','z']
    # Exact ties break by content-derived order (best branch rank, then lexical rank), not by the key, whose
    # revision part changes when the same content is loaded again: 'zz' (lexical #1) beats 'aa' (vector #1).
    assert d.call('fuse',lexical=['zz','yy'],vector=['aa','bb']) == ['zz','aa','yy','bb']
    # Reranked head first in reranker order, then the untouched fused tail; a result that does not
    # match its candidates is rejected (recall then keeps the fused order, degradation reranker-unavailable).
    assert d.call('rerankMerge',ranked=['a','b','c','d'],head=['a','b','c'],order=['c','a','b']) == ['c','a','b','d']
    assert 'does not match' in d.request('rerankMerge',ranked=['a','b'],head=['a','b'],order=['a','z'])['error']
    minimum = 'a:'+manifest['target']['epoch']+':1'
    request = {**binding,'principal':'worker','calls':[{'name':'wiki_recall','arguments':{'query':query,'maxBytes':2048,'atLeast':minimum}}]}
    result = subprocess.run(['node','tests/runtime/mcp-client.mjs'],cwd=ROOT,input=json.dumps(request),
                            capture_output=True,text=True,timeout=60)
    assert result.returncode == 0, result.stdout+result.stderr
    result = json.loads(result.stdout)['results'][0]
    assert not result.get('isError'),result
    assert len(result['content'][0]['text'].encode()) <= 2048
    assert json.loads(result['content'][0]['text'])['coverage'] == 'hybrid-current'
    legacy = d.call('legacyRecall',binding=binding,input={'query':query})
    assert legacy['coverage'] == 'hybrid-current'
    assert legacy['evidence']['passages'][0]['revision'] == page.revision
    assert d.call('recall',binding=binding,input={'query':query,'atLeast':minimum[:-1]+'99'})['kind'] == 'not-ready'
    assert d.call('recall',binding=binding,input={'query':query,'atLeast':'b:foreign:1'})['kind'] == 'not-ready'


def test_stale_generation_never_returns_replaced_or_retired_heads(system):
    store, page, binding, d = system
    first = d.call('build',binding=binding)
    current = publish(store,page,'Replacement needle_zebra drives the engine.')
    stale = d.call('recall',binding=binding,input={'query':'needle_zebra'})
    assert stale['coverage'] == 'hybrid-stale'
    assert stale['snapshot']['sequence'] == 2
    assert stale['index']['indexedThrough']['sequence'] == 1
    assert stale['evidence']['passages'][0]['revision'] == current.revision
    assert all(p['revision'] != page.revision for p in stale['evidence']['passages'])
    assert d.call('recall',binding=binding,input={'query':'engine','coverage':'require-hybrid-current'})['kind'] == 'not-ready'
    publish(store,current,'Retired record',ChangeKind.RETIRE)
    retired = d.call('recall',binding=binding,input={'query':'engine'})
    assert retired['coverage'] == 'hybrid-stale'
    assert retired['evidence']['kind'] == 'no-matches'
    assert retired['snapshot']['sequence'] == 3
    assert first['target']['sequence'] == 1


def test_real_reader_is_pinned_across_promotion_and_cleanup(system):
    store, page, binding, d = system
    first = d.call('build',binding=binding)
    held = d.call('pin',binding=binding,id='old')
    before = tree(held['directory'])
    new = publish(store,page,'A replacement engine with a teal radiator.')
    second = d.call('build',binding=binding)
    assert second['generation'] != first['generation']
    assert d.call('cleanup',binding=binding) == []
    assert d.call('search',id='old',query='coolant circulation')
    assert tree(held['directory']) == before  # provider never opens the pinned files
    current = d.call('recall',binding=binding,input={'query':'teal radiator'})
    assert current['coverage'] == 'hybrid-current'
    assert current['index']['generation'] == second['generation']
    assert current['evidence']['passages'][0]['revision'] == new.revision
    d.call('release',id='old')
    assert d.call('cleanup',binding=binding) == [first['generation']]
    assert not Path(held['directory']).exists()
    assert not d.request('search',id='old',query='engine')['ok']


@pytest.mark.parametrize('mismatch',['project','epoch','future'])
def test_unusable_generation_cannot_claim_hybrid(system,mismatch):
    store, page, binding, d = system
    manifest = d.call('build',binding=binding)
    held = d.call('pin',binding=binding,id='edit-location')
    d.call('release',id='edit-location')
    path = Path(held['directory'])/'manifest.json'
    if mismatch == 'future': manifest['target']['sequence'] += 100
    else: manifest['target'][mismatch] = 'foreign'
    path.write_text(json.dumps(manifest))
    best = d.call('recall',binding=binding,input={'query':'amber engine'})
    assert best['coverage'] == 'lexical-only'
    assert best['evidence']['passages'][0]['revision'] == page.revision
    assert d.call('recall',binding=binding,input={'query':'engine','coverage':'require-hybrid-current'})['kind'] == 'not-ready'


def test_unavailable_cached_model_and_build_failure_keep_last_generation(system,tmp_path):
    store, page, binding, d = system
    first = d.call('build',binding=binding)
    missing_current = {**binding,'model':str(tmp_path/'absent.gguf')}
    assert d.call('recall',binding=missing_current,input={'query':'engine','coverage':'require-hybrid-current'})['kind'] == 'not-ready'
    publish(store,page,'New unindexed auburn engine.')
    missing = {**binding,'model':str(tmp_path/'absent.gguf')}
    assert not d.request('build',binding=missing)['ok']
    result = d.call('recall',binding=missing,input={'query':'auburn'})
    assert result['coverage'] == 'lexical-only'
    assert result['index']['generation'] == first['generation']
    assert d.call('recall',binding=missing,input={'query':'auburn','coverage':'require-hybrid-current'})['kind'] == 'not-ready'
    assert store.connect('a').execute('SELECT sequence FROM retrieval_generations WHERE project=?',('a',)).fetchone()[0] == 1
    assert store.get_outbox_status('a')['index:pending'] >= 1
    bogus = tmp_path/'unapproved.gguf';bogus.write_bytes(b'GGUF not approved')
    assert 'unapproved cached embedding hash' in d.request('build',binding={**binding,'model':str(bogus)})['error']
    held = d.call('pin',binding=binding,id='survived')
    assert held['manifest']['generation'] == first['generation']


def test_lf_spans_sources_links_and_complete_capacity(system):
    store, page, binding, d = system
    private = store.capture_source('a','Private','private_needle_should_not_be_public','synthetic://private')
    source = store.capture_source('a','Cited','private first line\npublic_evidence_line\nprivate last line','synthetic://cited')
    source_body = 'private first line\npublic_evidence_line\nprivate last line'
    citation = {'kind':'source','source':source,'revision':source,'hash':'h:'+hashlib.sha256(source_body.encode()).hexdigest(),'start':2,'end':2}
    store.create_page('a','citer','Citer','link_needle [[target]]','owner',[{'kind':'existing','citation':citation}])
    store.create_page('a','target','Target','\n'.join('Ukrainian рядок '+str(n) for n in range(70)),'owner')
    receipt = store.propose('a','engine',page.revision,ChangeKind.REPLACE,'Private proposal','proposal_needle_hidden','worker',[])
    assert receipt.kind == 'pending'
    snap = d.call('snapshot',binding=binding,query='private_needle_should_not_be_public')
    assert snap['lexical'] == []
    assert all(c['revision'] != private for c in snap['documents'])
    answer = d.call('recall',binding=binding,input={'query':'link_needle'})
    pages = answer['evidence']['passages']
    assert any(p.get('page') == 'target' for p in pages)
    assert any(p.get('source') == source and p['text'] == 'public_evidence_line' and p['start'] == 2 for p in pages)
    assert all('proposal_needle_hidden' not in p['text'] for p in pages)
    for p in pages:
        if p.get('page') == 'target':
            body = store.page('a','target').markdown
            assert p['text'] == '\n'.join(body.split('\n')[p['start']-1:p['end']])
            assert p['end']-p['start'] < 32
    long = store.create_page('a','long','Long','capacity_needle '+'ї'*4000,'owner')
    capacity = d.call('recall',binding=binding,input={'query':'capacity_needle','maxBytes':2048})
    assert capacity['kind'] == 'capacity'
    assert not d.request('recall',binding=binding,input={'query':'engine','maxBytes':256})['ok']


def test_fts_and_head_visibility_are_transactional_and_sequences_are_not_client_cached(system):
    store, page, binding, d = system
    second = connect_knowledge(binding['database'],'a')
    conn = store.connect('a')
    conn.execute('BEGIN IMMEDIATE')
    conn.execute("DELETE FROM retrieval_chunks WHERE project='a'")
    conn.execute("UPDATE page_heads SET state='retired' WHERE project='a'")
    before = retrieval.snapshot(second,'a','amber')
    assert before['lexical'] and before['snapshot']['sequence'] == 1
    conn.rollback()
    second.create_page('a','second','Second','second value','owner')
    store.create_page('a','third','Third','third value','owner')
    assert retrieval.snapshot(second,'a')['snapshot']['sequence'] == 3
    with pytest.raises(AuthorityError, match='validated generation'):
        store.process_outbox('a')
    assert store.get_outbox_status('a')['index:pending'] == 3


def test_build_acknowledges_only_captured_target_during_concurrent_publication(system):
    store, page, binding, d = system
    command = ['node','node_modules/tsx/dist/cli.mjs','src/retrieval/build-index.ts',
               binding['database'],binding['project'],binding['indexRoot'],binding['model']]
    process = subprocess.Popen(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    deadline = time.monotonic()+20
    while not list(Path(binding['indexRoot']).glob('*/.build-*/documents/*.md')):
        assert process.poll() is None, process.communicate()
        assert time.monotonic()<deadline,'build did not capture its snapshot'
        time.sleep(.01)
    updated = publish(store,page,'Concurrent newest_copper engine.')
    stdout, stderr = process.communicate(timeout=60)
    assert process.returncode == 0,stdout+stderr
    assert json.loads(stdout)['target']['sequence'] == 1
    assert store.connect('a').execute('SELECT sequence FROM retrieval_generations WHERE project=?',('a',)).fetchone()[0] == 1
    assert store.get_outbox_status('a')['index:pending'] == 1
    result = d.call('recall',binding=binding,input={'query':'newest_copper'})
    assert result['coverage'] == 'hybrid-stale'
    assert result['snapshot']['sequence'] == 2
    assert result['index']['indexedThrough']['sequence'] == 1
    assert result['evidence']['passages'][0]['revision'] == updated.revision


def test_dead_reader_lease_is_reclaimed_without_deleting_live_generation(system):
    store, page, binding, d = system
    first = d.call('build',binding=binding)
    abandoned = Driver()
    abandoned.call('pin',binding=binding,id='abandoned')
    abandoned.proc.stdin.write(json.dumps({'action':'crash'})+'\n')
    abandoned.proc.stdin.flush()
    assert abandoned.proc.wait(timeout=10) == 19
    abandoned.proc.stdin.close()
    publish(store,page,'Next engine generation.')
    second = d.call('build',binding=binding)
    assert d.call('cleanup',binding=binding) == [first['generation']]
    assert d.call('recall',binding=binding,input={'query':'engine'})['index']['generation'] == second['generation']


def test_corrupt_or_deleted_derived_indexes_do_not_destroy_accepted_knowledge(system):
    store, page, binding, d = system
    d.call('build',binding=binding)
    pin = d.call('pin',binding=binding,id='location')
    d.call('release',id='location')
    with (Path(pin['directory'])/'index.sqlite').open('ab') as output:
        output.write(b'corruption fixture')
    result = d.call('recall',binding=binding,input={'query':'amber'})
    assert result['coverage'] == 'lexical-only' and result['degradation'] == 'generation-integrity'
    assert d.call('recall',binding=binding,input={'query':'amber','coverage':'require-hybrid-current'})['kind'] == 'not-ready'
    shutil.rmtree(binding['indexRoot'])
    assert store.page('a','engine').markdown == page.markdown
    rebuilt = d.call('build',binding=binding)
    current = d.call('recall',binding=binding,input={'query':'amber'})
    assert current['coverage'] == 'hybrid-current'
    assert current['index']['generation'] == rebuilt['generation']


def test_ranked_spans_preserve_document_diversity(system):
    store, page, binding, d = system
    store.create_page('a','large','Large','\n'.join(['diversity_needle']*320),'owner')
    for name in ('one','two'):
        store.create_page('a',name,name,'diversity_needle '+'unrelated '*100,'owner')
    result = d.call('recall',binding=binding,input={'query':'diversity_needle'})
    passages = result['evidence']['passages']
    assert len(passages) == 10
    assert {p['page'] for p in passages} == {'large','one','two'}


def test_reranker_admission_and_fallbacks(system, tmp_path):
    """Machine-wide non-blocking kernel-lock admission, holder-death release and fail-closed fallbacks. None of these paths
    loads a reranker model: each must keep the exact fused evidence and report its degradation."""
    store, page, binding, d = system
    store.create_page('a','pump','Pump','The sapphire coolant pump is serviced yearly.','owner')
    d.call('build',binding=binding)
    lock = tmp_path/'rerank.lock'
    d.call('setEnv',name='WIKI_RERANK_LOCK',value=str(lock))
    ask = dict(query='sapphire coolant pump',coverage='require-hybrid-current')
    base = d.call('recall',binding=binding,input=ask)
    assert 'degradation' not in base and base['evidence']['passages']
    bad = tmp_path/'bad.gguf'
    bad.write_bytes(b'not the approved reranker')
    reranked = {**binding,'reranker':{'model':str(bad)}}
    # Another process (this test) holds the kernel lock: busy, fused evidence, nothing loaded or queued.
    import fcntl
    holder = open(lock,'a')
    fcntl.flock(holder,fcntl.LOCK_EX)
    busy = d.call('recall',binding=reranked,input=ask)
    assert busy['degradation'] == 'reranker-busy' and busy['evidence'] == base['evidence']
    holder.close()  # releases the kernel lock
    # Admitted, but the unapproved model fails closed; the lock is released again afterwards.
    failed = d.call('recall',binding=reranked,input=ask)
    assert failed['degradation'] == 'reranker-unavailable' and failed['evidence'] == base['evidence']
    probe = open(lock,'a')
    fcntl.flock(probe,fcntl.LOCK_EX|fcntl.LOCK_NB)  # would raise if recall had kept it
    probe.close()
    # A holder that dies releases the lock (kernel), with no stale state to reclaim.
    dying = subprocess.Popen([sys.executable,'-c','import fcntl,sys,time; f=open(sys.argv[1],"a"); fcntl.flock(f,fcntl.LOCK_EX); print("held",flush=True); time.sleep(60)',str(lock)],
                             stdout=subprocess.PIPE,text=True)
    assert dying.stdout.readline().strip() == 'held'
    assert d.call('lockTry',path=str(lock)) is False
    dying.kill(); dying.wait()
    assert d.call('lockTry',path=str(lock)) is True
    assert d.call('lockTry',path=str(lock)) is False  # held by this same process: still exclusive
    d.call('lockRelease')
    assert d.call('lockTry',path=str(lock)) is True
    d.call('lockRelease')
    # A generation lock held past the 5 s timeout is reported as load, not as corruption.
    glock = open(Path(binding['indexRoot'])/hashlib.sha256(b'a').hexdigest()/'.lock','a')
    fcntl.flock(glock,fcntl.LOCK_EX)
    try:
        slow = d.call('recall',binding=binding,input=dict(query='sapphire coolant pump'))
    finally:
        glock.close()
    assert slow['coverage'] == 'lexical-only' and slow['degradation'] == 'generation-lock-unavailable'
    # An invalid reranker configuration fails closed instead of ranking with surprising limits.
    invalid = d.call('recall',binding={**binding,'reranker':{'model':str(bad),'depth':0}},input=ask)
    assert invalid['degradation'] == 'reranker-unavailable' and invalid['evidence'] == base['evidence']
    # Exactly one finite score per candidate; ties keep fused order.
    assert d.call('scores',keys=['a','b','c'],scores=[0.1,0.9,0.1]) == ['b','a','c']
    for scores in ([0.1],[0.1,None],[0.1,0.2,0.3],'x'):
        assert 'malformed' in d.request('scores',keys=['a','b'],scores=scores)['error']
    # Protected front: exact identifier hits, then the first chunk of each top-n fused object, then the rest.
    objects = {'a1':'A','a2':'A','b1':'B','c1':'C','d1':'D','x1':'X'}
    assert d.call('protect',ranked=['c1','d1','b1','a1','a2'],exact=[],fused=['a1','a2','b1','c1','d1'],n=2,objects=objects) == ['a1','b1','c1','d1','a2']
    assert d.call('protect',ranked=['c1','d1','b1','a1'],exact=['x1','zz'],fused=['a1','b1'],n=1,objects=objects) == ['x1','a1','c1','d1','b1']
    assert d.call('protect',ranked=['c1','a1'],exact=[],fused=['a1','c1'],n=0,objects=objects) == ['c1','a1']
    # The merge accepts only an exact permutation of its candidates.
    for order in (['a','b','z'],['a','a'],['a']):
        assert 'does not match' in d.request('rerankMerge',ranked=['a','b','c'],head=['a','b'],order=order)['error']
