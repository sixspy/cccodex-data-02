"""隔离条目人工放行：单条申请、必填备注、72 小时同编码冷却、正式库留痕。"""

import sqlite3

from app.db import db_transaction
from app.services.dedup import normalize_item_key

RELEASE_COOLDOWN_HOURS = 72


def release_to_main(job_id: int, quarantine_id: int, remark: str) -> dict:
    """把一条隔离记录放行入正式库。任一规则不满足即整体回滚并抛 ValueError。"""
    remark = (remark or "").strip()
    if not remark:
        raise ValueError("放行须填写非空备注")

    with db_transaction() as tx:
        q = tx.execute(
            "SELECT * FROM quarantine_records WHERE id = ? AND job_id = ?",
            (quarantine_id, job_id),
        ).fetchone()
        if q is None:
            raise ValueError("隔离条目不存在或已被处理")

        sku = q["sku"]
        if sku:
            # 同编码 72 小时内已有放行记录的不得再次放行
            recent = tx.execute(
                """
                SELECT released_at FROM release_logs
                WHERE sku = ?
                  AND released_at > datetime('now', ?)
                LIMIT 1
                """,
                (sku, f"-{RELEASE_COOLDOWN_HOURS} hours"),
            ).fetchone()
            if recent is not None:
                raise ValueError(
                    f"编码 {sku} 在 {RELEASE_COOLDOWN_HOURS} 小时内已有放行记录"
                    f"（{recent['released_at']}），不得再次放行"
                )
            # 隔离与正式库不得同编码共存
            dup = tx.execute(
                "SELECT 1 FROM crawl_records WHERE job_id = ? AND sku = ? LIMIT 1",
                (job_id, sku),
            ).fetchone()
            if dup is not None:
                raise ValueError(f"正式库已存在编码 {sku}，不得放行")

        job = tx.execute(
            "SELECT * FROM crawl_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        key = normalize_item_key(job["seed_path"], q["title"])
        try:
            tx.execute(
                """
                INSERT INTO crawl_records (job_id, item_key, sku, title, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (job_id, key, sku, q["title"], q["payload_json"]),
            )
        except sqlite3.IntegrityError:
            raise ValueError("正式库已存在相同条目，不得放行")

        tx.execute("DELETE FROM quarantine_records WHERE id = ?", (quarantine_id,))
        # 正式库留痕：谁、何时、以何备注放行了哪条
        tx.execute(
            """
            INSERT INTO release_logs (job_id, item_key, sku, title, remark)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job_id, key, sku, q["title"], remark),
        )

    return {"item_key": key, "sku": sku, "title": q["title"]}
