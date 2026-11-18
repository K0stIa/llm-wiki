#!/usr/bin/env python3
"""Experimental worker-only Unix boundary. Not a production MCP/host deployment.

The trusted operator launches this outside the worker mount namespace. Only the
socket is exposed to sandbox_worker.py. Database/project/principal cannot be
supplied by requests. Hybrid recall and curator operations are NOT exposed.
"""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys

MAX_REQUEST = 2 * 1024 * 1024
FIELDS = {
    'wiki_host_binding': (set(), set()),
    'wiki_host_propose': ({'page','baseRevision','changeKind','title','markdown','key','expectedEpoch'}, {'sources'}),
    'wiki_page': ({'page'}, {'revision'}),
    'wiki_read': ({'page'}, {'revision'}),
    'wiki_operation': ({'key'}, set()),
    'wiki_propose': ({'page','baseRevision','changeKind','title','markdown','key'}, {'sources'}),
}

def validate(payload):
    if not isinstance(payload,dict) or set(payload) != {'tool','args'}:
        raise ValueError('invalid envelope')
    tool=payload['tool'];args=payload['args']
    if not isinstance(tool,str) or tool not in FIELDS or not isinstance(args,dict):
        raise ValueError('invalid tool')
    required,optional=FIELDS[tool]
    if not required <= set(args) or set(args)-required-optional:
        raise ValueError('invalid fields')
    for key,value in args.items():
        if key=='sources':
            if not isinstance(value,list) or len(value)>100 or any(not isinstance(x,dict) for x in value):
                raise ValueError('invalid sources')
            continue
        cap=1024*1024 if key=='markdown' else 4096 if key=='title' else 512
        if not isinstance(value,str) or len(value)>cap or (not value and key not in ('title','markdown')):
            raise ValueError('invalid value')
        if key in ('page','revision','baseRevision','key') and ('/' in value or '\\' in value or '\x00' in value or value in ('.','..')):
            raise ValueError('path-like identity')
    if tool in ('wiki_propose','wiki_host_propose') and args['changeKind'] not in ('replace','retire'):
        raise ValueError('invalid change')
    return tool,args

def main():
    if len(sys.argv)!=4:
        raise SystemExit('Usage: worker_service.py DATABASE PROJECT SOCKET')
    database,project,path=sys.argv[1:]
    database=str(Path(database).resolve(strict=True))
    path=Path(path).absolute()
    # Never remove or replace an existing file/socket owned by another run.
    if path.exists() or path.is_symlink():
        raise SystemExit('socket path already exists')
    rpc=Path(__file__).with_name('authority_rpc.py')
    with socket.socket(socket.AF_UNIX) as server:
        old=os.umask(0o177)
        try:server.bind(str(path))
        finally:os.umask(old)
        inode=path.stat().st_ino
        server.listen(16)
        def stop(*_):raise KeyboardInterrupt
        signal.signal(signal.SIGTERM,stop)
        print('READY',flush=True)
        try:
            while True:
                client,_=server.accept()
                with client:
                    client.settimeout(3)
                    try:
                        with client.makefile('rb') as stream:
                            raw=stream.readline(MAX_REQUEST+1)
                        if len(raw)>MAX_REQUEST or not raw.endswith(b'\n'):
                            raise ValueError('size/framing')
                        tool,args=validate(json.loads(raw))
                        result=subprocess.run([sys.executable,str(rpc),database,project,'worker',tool],input=json.dumps(args),text=True,capture_output=True,timeout=30)
                        if result.returncode:
                            reply={'error':'operation denied'}
                        else:
                            reply={'result':json.loads(result.stdout)}
                    except (ValueError,TypeError,RecursionError,OSError,subprocess.SubprocessError):
                        reply={'error':'request denied'}
                    try:client.sendall(json.dumps(reply,ensure_ascii=False).encode()+b'\n')
                    except OSError:pass
        except KeyboardInterrupt:
            pass
        finally:
            try:
                if path.stat().st_ino==inode:path.unlink()
            except FileNotFoundError:pass

if __name__=='__main__':main()
