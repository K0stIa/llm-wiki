"""Opt-in TRUSTED HOST library, not a model tool or an integrated MCP adapter.

Caller must supply authenticated, stable session/call IDs and initial project
epoch out-of-band. Live epoch is rechecked; caller owns endpoint authenticity.
Never enroll automatically on missing/corrupt/restored journal or epoch mismatch.
"""
from contextlib import closing
import json
import os
from pathlib import Path
import socket
import sqlite3
import hashlib

import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'authority'))
from worker_service import validate, MAX_REQUEST
import faults


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def identity(value):
    if not isinstance(value,str) or not value or len(value)>512 or '\x00' in value:
        raise ValueError('trusted identity required')
    return value


class Journal:
    @staticmethod
    def enroll(path,*,project,principal,epoch):
        """Explicit first enrollment only. Never an automatic recovery action."""
        scope=[identity(project),identity(principal),identity(epoch)]
        if principal!='worker':raise ValueError('only worker service supported')
        # Exclusive create prevents accidental replacement of existing history.
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
        with closing(sqlite3.connect(path)) as c:
            c.execute('PRAGMA synchronous=FULL')
            c.execute('CREATE TABLE scope(value TEXT NOT NULL)')
            c.execute('INSERT INTO scope VALUES (?)',(canonical(scope),))
            c.execute('CREATE TABLE calls(session TEXT NOT NULL, call TEXT NOT NULL, payload TEXT NOT NULL, request TEXT NOT NULL, receipt TEXT, PRIMARY KEY(session,call))')
            c.commit()
        # SQLite syncs database; also persist its directory entry on enrollment.
        directory=os.open(str(Path(path).absolute().parent),os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)

    def __init__(self,path,*,project,principal,epoch):
        self.path=Path(path).absolute()
        self.scope=canonical([identity(project),identity(principal),identity(epoch)])
        if principal!='worker':raise ValueError('only worker service supported')
        with closing(self._connect()):pass

    def _connect(self):
        # mode=rw never creates a missing database after a host restart.
        c=sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=10)
        try:
            c.execute('PRAGMA synchronous=FULL')
            rows=c.execute('SELECT value FROM scope').fetchall()
            if rows!=[(self.scope,)]:raise ValueError('journal scope/epoch mismatch; operator recovery required')
            return c
        except BaseException:
            c.close();raise

    def prepare(self,session,call,args):
        """Commit immutable payload and one key BEFORE any network side effect."""
        identity(session);identity(call)
        if not isinstance(args,dict) or {'key','expectedEpoch'} & set(args):raise ValueError('model keys forbidden')
        payload=canonical(args)
        request={'tool':'wiki_host_propose','args':{**json.loads(payload),'key':'host-'+hashlib.sha256(canonical(['host-journal-v1',*json.loads(self.scope),session,call]).encode()).hexdigest(),'expectedEpoch':json.loads(self.scope)[2]}}
        validate(request)
        raw=canonical(request)
        if len(raw.encode())+1>MAX_REQUEST:raise ValueError('request too large')
        c=self._connect()
        try:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT payload,request FROM calls WHERE session=? AND call=?',(session,call)).fetchone()
            if row:
                if row[0]!=payload:raise ValueError('identity already bound to different payload')
                raw=row[1]
            else:c.execute('INSERT INTO calls VALUES (?,?,?,?,NULL)',(session,call,payload,raw))
            c.commit()
            return json.loads(raw)
        except BaseException:
            c.rollback();raise
        finally:c.close()

    @staticmethod
    def send(endpoint,request):
        """Low-level trusted transport. No receipt commit (crash-safe replay)."""
        raw=canonical(request).encode()+b'\n'
        with socket.socket(socket.AF_UNIX) as c:
            c.settimeout(35);c.connect(str(endpoint));c.sendall(raw);c.shutdown(socket.SHUT_WR)
            with c.makefile('rb') as stream:reply=stream.readline(MAX_REQUEST+1)
        if len(reply)>MAX_REQUEST or not reply.endswith(b'\n'):raise ValueError('invalid response framing')
        result=json.loads(reply)
        if not isinstance(result,dict) or set(result)!={'result'}:raise ValueError('authority denied request; no fresh-key retry permitted')
        return result

    def execute(self,endpoint,session,call,args):
        binding=self.send(endpoint,{'tool':'wiki_host_binding','args':{}})['result']
        expected=dict(zip(('project','principal','epoch'),json.loads(self.scope)))
        if binding!=expected:raise ValueError('live authority binding/epoch mismatch')
        request=self.prepare(session,call,args)
        faults.point('journal.after-prepare')
        c=self._connect()
        try:row=c.execute('SELECT receipt FROM calls WHERE session=? AND call=?',(session,call)).fetchone()
        finally:c.close()
        if row[0] is not None:
            operation=self.send(endpoint,{'tool':'wiki_operation','args':{'key':request['args']['key']}})['result']
            if not isinstance(operation,dict) or operation.get('kind')=='unknown' or operation.get('status') in ('failed',None):
                raise ValueError('cached receipt no longer backed by live operation')
            # Recheck binding after querying the operation, including cached paths.
            if self.send(endpoint,{'tool':'wiki_host_binding','args':{}})['result']!=expected:
                raise ValueError('live authority epoch changed')
            return json.loads(row[0])
        reply=self.send(endpoint,request)
        faults.point('journal.after-send')
        raw=canonical(reply)
        c=self._connect()
        try:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT receipt FROM calls WHERE session=? AND call=?',(session,call)).fetchone()[0]
            if old is not None and old!=raw:raise ValueError('contradictory receipt')
            c.execute('UPDATE calls SET receipt=? WHERE session=? AND call=?',(raw,session,call))
            c.commit()
        except BaseException:
            c.rollback();raise
        finally:c.close()
        faults.point('journal.after-receipt')
        return reply

    def unfinished(self):
        """Prepared calls whose receipt was never recorded, oldest first."""
        c=self._connect()
        try:return [(r[0],r[1],json.loads(r[2])) for r in c.execute('SELECT session,call,payload FROM calls WHERE receipt IS NULL ORDER BY rowid')]
        finally:c.close()

    def recover(self,endpoint):
        """Replay every unfinished call with its ORIGINAL journaled key and payload.

        Run by the trusted adapter on restart, before accepting new calls. A
        replay never mints a new key: the authority returns the original
        receipt if the first send committed, or admits the request once if it
        did not.
        """
        return [(session,call,self.execute(endpoint,session,call,payload)) for session,call,payload in self.unfinished()]
