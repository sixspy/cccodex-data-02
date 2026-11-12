import json
import sqlite3

from flask import current_app

from app.db import db_transaction, get_db
from app.services.dedup import normalize_item_key
from app.services.mock_catalog import get_catalog, parse_catalog_html, render_catalog_page
from app.services.validate import validate_item


class JobConflictError(Exception):
    """任务状态不允许再次触发（运行中 / 已完成）。"""


def _claim_job(db, job_id: int) -> sqlite3.Row:
    """原子占位：仅 draft / failed 可启动，运行中或已完成一律拒绝。"""
    job = db.execute(
        "SELECT * FROM crawl_jobs WHERE id = ?", (job_id,)
    ).fetchone()
    if job is None:
        raise ValueError("任务不存在")
    if job["status"] == "running":
        raise JobConflictError("任务正在运行中，拒绝重复触发")
    if job["status"] == "done":
        raise JobConflictError("任务已完成，如需重跑请新建任务")
    cur = db.execute(
        """
        UPDATE crawl_jobs
        SET status = 'running', finished_at = NULL, message = NULL
        WHERE id = ? AND status IN ('draft', 'failed')
        """,
        (job_id,),
    )
    db.commit()
    if cur.rowcount == 0:
        # 并发下另一个请求已占位
        raise JobConflictError("任务正在运行中，拒绝重复触发")
    return job


def run_job(job_id: int) -> dict:
    db = get_db()
    job = _claim_job(db, job_id)
    seed = job["seed_path"]
    try:
        return _run_claimed(job_id, seed)
    except JobConflictError:
        raise
    except Exception as e:
        db.execute(
            "UPDATE crawl_jobs SET status = 'failed', finished_at = datetime('now'),"
            " message = ? WHERE id = ?",
            (f"运行异常：{e}", job_id),
        )
        db.commit()
        raise


def _run_claimed(job_id: int, seed: str) -> dict:
    db = get_db()
    catalog = get_catalog(seed)
    if catalog is None:
        with db_transaction() as tx:
            tx.execute(
                "UPDATE crawl_jobs SET status = 'failed', finished_at = datetime('now'),"
                " message = '未知种子路径' WHERE id = ?",
                (job_id,),
            )
        return {
            "status": "failed", "reason": "unknown seed",
            "inserted": 0, "skipped_dup": 0, "quarantined": 0, "total_source": 0,
        }

    html = render_catalog_page(seed)
    if isinstance(html, tuple):
        html = html[0]
    items = parse_catalog_html(html, seed)

    inserted = 0
    skipped_dup = 0
    quarantined = 0
    invalid_seen = 0
    with db_transaction() as tx:
        for it in items:
            key = normalize_item_key(seed, it["title"])
            sku = (it.get("sku") or "").strip()
            reason = validate_item(it, catalog["prefix"])
            if reason is not None:
                invalid_seen += 1
                # 隔离与正式库不得同编码共存；同任务内编码唯一
                if sku and _code_exists(tx, job_id, sku):
                    skipped_dup += 1
                    continue
                try:
                    tx.execute(
                        """
                        INSERT INTO quarantine_records
                            (job_id, item_key, sku, title, reason, payload_json)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            job_id, key, sku, it["title"], reason,
                            json.dumps(it, ensure_ascii=False),
                        ),
                    )
                    quarantined += 1
                except sqlite3.IntegrityError:
                    skipped_dup += 1
                continue
            if sku and _code_in_quarantine(tx, job_id, sku):
                # 编码被隔离条目占用，留待人工放行裁决
                skipped_dup += 1
                continue
            try:
                tx.execute(
                    """
                    INSERT INTO crawl_records (job_id, item_key, sku, title, payload_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (job_id, key, sku, it["title"], json.dumps(it, ensure_ascii=False)),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                skipped_dup += 1

        # 全部非法且新写入为零 → 任务失败（含重跑时非法条目已在隔离库的情形）
        if inserted == 0 and invalid_seen > 0:
            status = "failed"
            message = (
                f"解析 {len(items)} 条，{invalid_seen} 条不合法"
                f"（本次新隔离 {quarantined} 条），新写入为零，任务失败"
            )
        else:
            status = "done"
            message = None
        tx.execute(
            """
            UPDATE crawl_jobs
            SET status = ?, finished_at = datetime('now'), message = ?,
                last_inserted = ?, last_skipped = ?, last_quarantined = ?
            WHERE id = ?
            """,
            (status, message, inserted, skipped_dup, quarantined, job_id),
        )

    current_app.logger.info(
        "job %s finished status=%s inserted=%s skipped_dup=%s quarantined=%s",
        job_id, status, inserted, skipped_dup, quarantined,
    )
    return {
        "status": status,
        "message": message,
        "inserted": inserted,
        "skipped_dup": skipped_dup,
        "quarantined": quarantined,
        "total_source": len(items),
    }


def _code_exists(tx, job_id: int, sku: str) -> bool:
    """同任务内正式库或隔离库已占该编码。"""
    if _code_in_quarantine(tx, job_id, sku):
        return True
    row = tx.execute(
        "SELECT 1 FROM crawl_records WHERE job_id = ? AND sku = ? LIMIT 1",
        (job_id, sku),
    ).fetchone()
    return row is not None


def _code_in_quarantine(tx, job_id: int, sku: str) -> bool:
    row = tx.execute(
        "SELECT 1 FROM quarantine_records WHERE job_id = ? AND sku = ? LIMIT 1",
        (job_id, sku),
    ).fetchone()
    return row is not None
