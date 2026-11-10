"""Shared fixtures for hypothesis tests.

All tests run against a temporary SQLite database with WAL mode.
Each test gets a clean database.
"""
import sqlite3
import tempfile
import os
from pathlib import Path
import pytest


@pytest.fixture()
def db_path(tmp_path):
    """Temporary WAL-mode SQLite database."""
    path = tmp_path / "wiki.db"
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""
        CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            epoch TEXT NOT NULL,
            sequence INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE page_heads (
            project TEXT NOT NULL,
            page TEXT NOT NULL,
            revision TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('active','retired')),
            PRIMARY KEY(project, page)
        )
    """)
    conn.execute("""
        CREATE TABLE page_revisions (
            revision TEXT PRIMARY KEY,
            project TEXT NOT NULL,
            page TEXT NOT NULL,
            base_revision TEXT,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('active','retired')),
            FOREIGN KEY(project, page) REFERENCES page_heads(project, page)
        )
    """)
    conn.execute("""
        CREATE TABLE proposals (
            proposal_id TEXT PRIMARY KEY,
            project TEXT NOT NULL,
            page TEXT NOT NULL,
            base_revision TEXT NOT NULL,
            change_body TEXT NOT NULL,
            title TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('pending','blocked','decided')),
            decision TEXT,
            rejected_reason TEXT,
            FOREIGN KEY(project, page) REFERENCES page_heads(project, page)
        )
    """)
    conn.execute("""
        CREATE TABLE proposal_keys (
            key TEXT PRIMARY KEY,
            proposal_id TEXT NOT NULL UNIQUE,
            project TEXT NOT NULL,
            page TEXT NOT NULL,
            base_revision TEXT NOT NULL,
            UNIQUE(key),
            FOREIGN KEY(project, page) REFERENCES page_heads(project, page)
        )
    """)
    conn.execute("""
        CREATE TABLE decisions (
            proposal_id TEXT PRIMARY KEY,
            decision_kind TEXT NOT NULL CHECK(decision_kind IN ('publish','reject')),
            decision_json TEXT NOT NULL,
            review_digest TEXT,
            FOREIGN KEY(proposal_id) REFERENCES proposals(proposal_id)
        )
    """)
    conn.execute("""
        CREATE TABLE operations (
            op_key TEXT PRIMARY KEY,
            project TEXT NOT NULL,
            principal TEXT NOT NULL,
            request_digest TEXT NOT NULL,
            result_digest TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('submitted','committed','failed')),
            FOREIGN KEY(project) REFERENCES projects(id)
        )
    """)
    conn.commit()
    yield path
    conn.close()


@pytest.fixture()
def conn(db_path):
    """Connection to the temporary database."""
    c = sqlite3.connect(str(db_path))
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=FULL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


@pytest.fixture()
def sample_project(conn):
    """A sample project row."""
    conn.execute("INSERT INTO projects VALUES ('proj-001', 'epoch-1', 0)")
    conn.execute("""
        INSERT INTO page_heads VALUES ('proj-001', 'page-a', 'rev-0', 'active')
    """)
    conn.execute("""
        INSERT INTO page_revisions VALUES ('rev-0', 'proj-001', 'page-a', NULL,
            'Initial page', 'body content', 'active')
    """)
    conn.commit()
    return conn
