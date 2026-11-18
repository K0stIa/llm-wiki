"""Private file-argument RPC for the synchronous TypeScript authority bridge."""
import dataclasses
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'mcp'))
from authority_rpc import dispatch
from authority import connect_knowledge
import recovery


def handle(request):
    op = request['operation']
    if op == 'backup':
        return recovery.backup(request['database'], request['project'], request['directory'])
    if op == 'restore':
        return recovery.restore(request['backupPath'], request['targetDirectory'])
    database, project = request['database'], request['project']
    if op == 'connect':
        store = connect_knowledge(database, project)
        try:
            row = store.connect(project).execute('SELECT epoch,sequence FROM projects WHERE id=?',(project,)).fetchone()
            return {'kind':'connected','project':project,'dbPath':str(Path(database).resolve()),'epoch':row[0],'sequence':row[1]}
        finally:
            store.disconnect()
    if op == 'create':
        store = connect_knowledge(database, project)
        try:
            return {'kind':'page', **dataclasses.asdict(store.create_page(project, request['page'], request['title'], request['markdown'], request['principal']))}
        finally:
            store.disconnect()
    principal = request.get('principal','worker')
    args = request['args']
    result = dispatch(database, project, principal, op, args)
    if op in ('wiki_page','wiki_read'):
        return {'kind':'page', **result}
    if op == 'wiki_propose' and result.get('kind')=='conflict':
        return None
    if op == 'wiki_operation' and result.get('kind')!='unknown':
        return {'kind':'operation', **result}
    if op == 'wiki_curator_pending':
        return {'kind':'pending-list', **result}
    return result


if __name__ == '__main__':
    try:
        request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
        print(json.dumps(handle(request), ensure_ascii=False, allow_nan=False))
    except Exception as error:
        print(json.dumps({'kind':'error','error':type(error).__name__,'message':str(error)}, ensure_ascii=False))
        sys.exit(1)
