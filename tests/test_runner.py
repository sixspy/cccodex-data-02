import pytest

from app.db import get_db
from app.services.runner import JobConflictError, run_job


def login(client):
    return client.post(
        "/login",
        data={"username": "admin", "password": "123456"},
        follow_redirects=True,
    )


def create_job(client, name, seed):
    client.post(
        "/jobs",
        data={"name": name, "seed_path": seed},
        follow_redirects=True,
    )


def last_job_id(app):
    with app.app_context():
        return get_db().execute(
            "SELECT MAX(id) AS id FROM crawl_jobs"
        ).fetchone()["id"]


def test_alpha_partial_success_with_quarantine(app, client):
    """部分合法：合法入正式库、非法入隔离库，任务成功并给出三向计数。"""
    login(client)
    create_job(client, "alpha 首轮", "/mock/catalog/alpha")
    job_id = last_job_id(app)
    with app.app_context():
        summary = run_job(job_id)
    assert summary["status"] == "done"
    assert summary["inserted"] == 2
    assert summary["skipped_dup"] == 1
    assert summary["quarantined"] == 4
    assert summary["total_source"] == 7


def test_invalid_items_not_in_main_library(app, client):
    """非法样本不进正式库，只进隔离库并带中文非法原因。"""
    login(client)
    create_job(client, "alpha 校验", "/mock/catalog/alpha")
    job_id = last_job_id(app)
    with app.app_context():
        run_job(job_id)
        db = get_db()
        main_skus = {
            r["sku"]
            for r in db.execute(
                "SELECT sku FROM crawl_records WHERE job_id = ?", (job_id,)
            )
        }
        rows = db.execute(
            "SELECT sku, reason FROM quarantine_records WHERE job_id = ?", (job_id,)
        ).fetchall()
    assert main_skus == {"A-001", "A-002"}
    reasons = {r["sku"]: r["reason"] for r in rows}
    assert reasons[""] == "编码为空"
    assert reasons["X-009"] == "编码格式不符"
    assert reasons["A-09"] == "编码格式不符"
    assert reasons["A-004"] == "标题不足四字"


def test_all_invalid_fails_job(app, client):
    """全部非法且新写入为零 → 任务失败并落提示。"""
    login(client)
    create_job(client, "gamma 全非法", "/mock/catalog/gamma")
    job_id = last_job_id(app)
    with app.app_context():
        summary = run_job(job_id)
        job = get_db().execute(
            "SELECT * FROM crawl_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    assert summary["status"] == "failed"
    assert summary["inserted"] == 0
    assert summary["quarantined"] == 3
    assert job["status"] == "failed"
    assert "新写入为零" in job["message"]
    # 重跑：非法条目已在隔离库、新写入仍为零 → 依旧失败
    with app.app_context():
        again = run_job(job_id)
        job = get_db().execute(
            "SELECT * FROM crawl_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    assert again["status"] == "failed"
    assert again["quarantined"] == 0
    assert job["status"] == "failed"


def test_same_code_unique_within_job(app, client):
    """同任务内编码唯一；非法条目的编码若已被正式库占用则跳过、不进隔离。"""
    login(client)
    create_job(client, "delta 编码唯一", "/mock/catalog/delta")
    job_id = last_job_id(app)
    with app.app_context():
        summary = run_job(job_id)
        db = get_db()
        main_skus = [
            r["sku"]
            for r in db.execute(
                "SELECT sku FROM crawl_records WHERE job_id = ?", (job_id,)
            )
        ]
        qua_skus = [
            r["sku"]
            for r in db.execute(
                "SELECT sku FROM quarantine_records WHERE job_id = ?", (job_id,)
            )
        ]
    assert summary["inserted"] == 1
    assert summary["skipped_dup"] == 2
    assert summary["quarantined"] == 1
    assert main_skus == ["D-001"]
    assert qua_skus == ["D-002"]


def test_running_job_rejects_second_trigger(app, client):
    """运行中再次触发须拒绝（服务层与 HTTP 层），且不破坏运行状态。"""
    login(client)
    create_job(client, "并发占位", "/mock/catalog/beta")
    job_id = last_job_id(app)
    with app.app_context():
        db = get_db()
        db.execute(
            "UPDATE crawl_jobs SET status = 'running' WHERE id = ?", (job_id,)
        )
        db.commit()
        with pytest.raises(JobConflictError):
            run_job(job_id)
    r = client.post(f"/jobs/{job_id}/run", follow_redirects=True)
    assert "拒绝重复触发" in r.get_data(as_text=True)
    with app.app_context():
        status = get_db().execute(
            "SELECT status FROM crawl_jobs WHERE id = ?", (job_id,)
        ).fetchone()["status"]
    assert status == "running"


def test_mock_catalog_http(client):
    r = client.get("/mock/catalog/alpha")
    assert r.status_code == 200
    assert "市政管线测绘记录表" in r.get_data(as_text=True)
