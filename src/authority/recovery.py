"""Operator-only SQLite snapshot backup and clean-instance restore."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import uuid


def file_hash(path):
    with open(path, 'rb') as stream:
        return 'h:' + hashlib.file_digest(stream, 'sha256').hexdigest()


def readonly(path, immutable=False):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro' + ('&immutable=1' if immutable else ''), uri=True)


def inspect(conn):
    if conn.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise ValueError('backup integrity check failed')
    if conn.execute('PRAGMA foreign_key_check').fetchone():
        raise ValueError('backup foreign keys are inconsistent')
    projects = [{'project': p, 'epoch': e, 'sequence': s} for p,e,s in conn.execute('SELECT id,epoch,sequence FROM projects ORDER BY id')]
    if not projects or any(not isinstance(p['project'],str) or not p['project'] or not isinstance(p['epoch'],str) or not p['epoch'] or type(p['sequence']) is not int or p['sequence']<0 for p in projects):
        raise ValueError('backup project metadata is invalid')
    return {'projects': projects,
            'authority': conn.execute('SELECT identity FROM authority_identity WHERE id=1').fetchone()[0],
            'revisionCount': conn.execute('SELECT COUNT(*) FROM page_revisions').fetchone()[0]}


def sync_file(path):
    with open(path, 'rb') as stream:
        os.fsync(stream.fileno())


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def backup(database, project, directory):
    # mode=ro must fail for missing databases, never create a substitute authority.
    source = readonly(database)
    stage = None
    try:
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='.wiki-backup-', dir=directory))
        path = stage/'authority.sqlite'
        dest = sqlite3.connect(path)
        try:
            deadline = time.monotonic() + 25
            def progress(status, remaining, total):
                if time.monotonic() > deadline:
                    raise TimeoutError('online backup exceeded 25 seconds')
            source.backup(dest, pages=64, progress=progress, sleep=.01)
            dest.execute('PRAGMA journal_mode=DELETE')
            metadata = inspect(dest)
        finally:
            dest.close()
        primary = next((p for p in metadata['projects'] if p['project'] == project), None)
        if primary is None:
            raise ValueError('backup project not found')
        manifest = {'version': 1, 'project': project, **metadata, 'hash': file_hash(path), 'sizeBytes': path.stat().st_size}
        (stage/'authority.sqlite.manifest.json').write_text(json.dumps(manifest, sort_keys=True), encoding='utf-8')
        sync_file(path)
        sync_file(stage/'authority.sqlite.manifest.json')
        sync_directory(stage)
        final = directory/('backup-' + uuid.uuid4().hex)
        os.rename(stage, final)
        stage = None
        sync_directory(directory)
        return {'kind': 'backup', 'path': str(final/'authority.sqlite'), 'manifestPath': str(final/'authority.sqlite.manifest.json'),
                'epoch': primary['epoch'], 'sequence': primary['sequence'], 'hash': manifest['hash'], 'sizeBytes': manifest['sizeBytes']}
    finally:
        source.close()
        if stage is not None:
            shutil.rmtree(stage)


def restore(backup_path, target_directory):
    started = time.monotonic()
    stage = None
    try:
        path = Path(backup_path)
        manifest = json.loads(Path(str(path)+'.manifest.json').read_text(encoding='utf-8'))
        if type(manifest.get('version')) is not int or manifest['version'] != 1 or manifest.get('hash') != file_hash(path) or manifest.get('sizeBytes') != path.stat().st_size:
            raise ValueError('backup manifest version/hash/size mismatch')
        target = Path(os.path.abspath(target_directory))
        if target.is_symlink() or (target.exists() and (not target.is_dir() or any(target.iterdir()))):
            raise FileExistsError('restore requires a clean destination')
        source = readonly(path, immutable=True)
        try:
            metadata = inspect(source)
            if json.dumps({k:manifest.get(k) for k in metadata}, sort_keys=True) != json.dumps(metadata, sort_keys=True):
                raise ValueError('backup manifest authority metadata mismatch')
            primary = next((p for p in metadata['projects'] if p['project'] == manifest.get('project')), None)
            if primary is None:
                raise ValueError('backup manifest project not found')
            target.parent.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix='.wiki-restore-', dir=target.parent))
            dest = sqlite3.connect(stage/'wiki-restored.sqlite')
            try:
                source.backup(dest)
                dest.execute('PRAGMA journal_mode=DELETE')
                dest.execute('PRAGMA foreign_keys=ON')
                epochs = []
                with dest:
                    for p in metadata['projects']:
                        epoch = uuid.uuid4().hex
                        dest.execute('UPDATE projects SET epoch=? WHERE id=?', (epoch, p['project']))
                        epochs.append({'project': p['project'], 'oldEpoch': p['epoch'], 'newEpoch': epoch, 'sequence': p['sequence']})
                    dest.execute('DELETE FROM retrieval_generations')
                    dest.execute('DELETE FROM index_state')
                    dest.execute('DELETE FROM outbox')
                    for kind in ('index','export'):
                        dest.execute('INSERT INTO outbox(project,page,revision,kind) SELECT project,page,revision,? FROM page_heads', (kind,))
                    dest.execute("UPDATE operations SET status='failed' WHERE op_key IN (SELECT k.key FROM proposal_keys k JOIN proposals p ON p.proposal_id=k.proposal_id WHERE p.state!='decided')")
                inspect(dest)
            finally:
                dest.close()
        finally:
            source.close()
        if manifest['hash'] != file_hash(path):
            raise ValueError('backup changed during restore')
        sync_file(stage/'wiki-restored.sqlite')
        sync_directory(stage)
        # Directory rename cannot replace an occupied destination. Never overwrite a live DB.
        os.rename(stage, target)
        stage = None
        sync_directory(target.parent)
        primary_epoch = next(p for p in epochs if p['project']==manifest['project'])
        return {'success': True, 'path': str(target/'wiki-restored.sqlite'), 'oldEpoch': primary_epoch['oldEpoch'],
                'newEpoch': primary_epoch['newEpoch'], 'restoredSequence': primary_epoch['sequence'],
                'retainedRevisions': metadata['revisionCount'], 'lostRevisions': None, 'projects': epochs,
                'elapsedSeconds': time.monotonic()-started}
    except Exception as error:
        return {'success': False, 'error': f'{type(error).__name__}: {error}'}
    finally:
        if stage is not None:
            shutil.rmtree(stage)
