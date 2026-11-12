import sqlite3
from contextlib import contextmanager

from flask import current_app, g


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@contextmanager
def db_transaction():
    db = get_db()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise


def _ensure_column(db, table: str, column: str, ddl: str) -> None:
    """给已存在的旧库补列（新库由 CREATE TABLE 一次建全）。"""
    cols = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db(app):
    with app.app_context():
        db = get_db()
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS crawl_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                seed_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                finished_at TEXT,
                message TEXT,
                last_inserted INTEGER NOT NULL DEFAULT 0,
                last_skipped INTEGER NOT NULL DEFAULT 0,
                last_quarantined INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS crawl_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL REFERENCES crawl_jobs(id) ON DELETE CASCADE,
                item_key TEXT NOT NULL,
                sku TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(job_id, item_key)
            );
            CREATE TABLE IF NOT EXISTS quarantine_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL REFERENCES crawl_jobs(id) ON DELETE CASCADE,
                item_key TEXT NOT NULL,
                sku TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                reason TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(job_id, item_key)
            );
            CREATE TABLE IF NOT EXISTS release_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL REFERENCES crawl_jobs(id) ON DELETE CASCADE,
                item_key TEXT NOT NULL,
                sku TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                remark TEXT NOT NULL,
                released_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            -- 同任务内编码唯一（空编码不参与约束，空编码条目本身即非法样本）
            CREATE UNIQUE INDEX IF NOT EXISTS idx_crawl_records_job_sku
                ON crawl_records(job_id, sku) WHERE sku <> '';
            CREATE UNIQUE INDEX IF NOT EXISTS idx_quarantine_job_sku
                ON quarantine_records(job_id, sku) WHERE sku <> '';
            """
        )
        # 旧库列补齐
        _ensure_column(db, "crawl_jobs", "message", "message TEXT")
        _ensure_column(
            db, "crawl_jobs", "last_inserted",
            "last_inserted INTEGER NOT NULL DEFAULT 0",
        )
        _ensure_column(
            db, "crawl_jobs", "last_skipped",
            "last_skipped INTEGER NOT NULL DEFAULT 0",
        )
        _ensure_column(
            db, "crawl_jobs", "last_quarantined",
            "last_quarantined INTEGER NOT NULL DEFAULT 0",
        )
        _ensure_column(db, "crawl_records", "sku", "sku TEXT NOT NULL DEFAULT ''")
        db.commit()
