#!/usr/bin/env python3
"""Run a local worker command with only the worker socket and system runtime.

No host HOME, authority database, curator credentials, network, inherited env,
or host /proc is mounted. This is a bounded test launcher, not model-host setup.
The service must be outside this mount namespace. It shares the operator UID;
other unsandboxed processes under that UID are NOT isolated by this launcher.
"""
import os
from pathlib import Path
import shutil
import stat
import sys


def main():
    if len(sys.argv)<4 or sys.argv[2]!='--':
        raise SystemExit('Usage: sandbox_worker.py SOCKET -- COMMAND [ARG...]')
    sock=Path(sys.argv[1]).resolve(strict=True)
    if not stat.S_ISSOCK(sock.stat().st_mode):
        raise SystemExit('worker endpoint must be a Unix socket')
    bwrap=shutil.which('bwrap')
    if not bwrap:raise SystemExit('bubblewrap is required; no unsandboxed fallback')
    args=[bwrap,'--clearenv','--setenv','PATH','/usr/bin:/bin','--setenv','HOME','/home/worker',
          '--ro-bind','/usr','/usr','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64',
          '--proc','/proc','--dev','/dev','--tmpfs','/tmp','--dir','/home','--dir','/home/worker',
          '--dir','/run','--ro-bind',str(sock),'/run/wiki.sock','--chdir','/tmp',
          '--unshare-pid','--unshare-net','--unshare-ipc','--unshare-uts','--new-session','--die-with-parent',
          '--',*sys.argv[3:]]
    os.execv(bwrap,args)

if __name__=='__main__':main()
