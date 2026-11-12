import pytest

from app.db import get_db
from app.services.release import release_to_main
from app.services.runner import run_job


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


def run_alpha(app, client, name):
    login(client)
    create_job(client, name, "/mock/catalog/alpha")
    job_id = last_job_id(app)
    with app.app_context():
        run_job(job_id)
    return job_id


def quarantine_id_of(app, job_id, sku):
    with app.app_context():
        row = get_db().execute(
            "SELECT id FROM quarantine_records WHERE job_id = ? AND sku = ?",
            (job_id, sku),
        ).fetchone()
    return row["id"] if row else None


def count(app, sql, args=()):
    with app.app_context():
        return get_db().execute(sql, args).fetchone()["c"]


def test_release_requires_nonempty_remark(app, client):
    """备注为空（含纯空白）拒放行，隔离/正式/留痕三处数据均不变。"""
    job_id = run_alpha(app, client, "alpha 空备注")
    qid = quarantine_id_of(app, job_id, "A-004")
    with app.app_context():
        with pytest.raises(ValueError):
            release_to_main(job_id, qid, "")
        with pytest.raises(ValueError):
            release_to_main(job_id, qid, "   ")
    r = client.post(
        f"/jobs/{job_id}/quarantine/{qid}/release",
        data={"remark": ""},
        follow_redirects=True,
    )
    assert "非空备注" in r.get_data(as_text=True)
    assert count(app, "SELECT COUNT(*) c FROM quarantine_records WHERE job_id = ?", (job_id,)) == 4
    assert count(app, "SELECT COUNT(*) c FROM crawl_records WHERE job_id = ?", (job_id,)) == 2
    assert count(app, "SELECT COUNT(*) c FROM release_logs") == 0


def test_release_moves_quarantine_to_main_with_trace(app, client):
    """放行后隔离侧消失，正式库新增记录并留痕（含备注）。"""
    job_id = run_alpha(app, client, "alpha 放行")
    qid = quarantine_id_of(app, job_id, "A-004")
    r = client.post(
        f"/jobs/{job_id}/quarantine/{qid}/release",
        data={"remark": "人工确认标题虽短但有效"},
        follow_redirects=True,
    )
    assert "已放行" in r.get_data(as_text=True)
    assert count(
        app,
        "SELECT COUNT(*) c FROM quarantine_records WHERE job_id = ? AND sku = 'A-004'",
        (job_id,),
    ) == 0
    assert count(
        app,
        "SELECT COUNT(*) c FROM crawl_records WHERE job_id = ? AND sku = 'A-004'",
        (job_id,),
    ) == 1
    with app.app_context():
        log = get_db().execute(
            "SELECT * FROM release_logs WHERE job_id = ? AND sku = 'A-004'", (job_id,)
        ).fetchone()
    assert log["remark"] == "人工确认标题虽短但有效"
    assert log["title"] == "短题"


def test_release_same_code_within_72h_rejected(app, client):
    """同编码 72 小时内已有放行记录 → 再次放行被拒，隔离条目保留。"""
    job1 = run_alpha(app, client, "首轮")
    with app.app_context():
        release_to_main(job1, quarantine_id_of(app, job1, "A-004"), "首轮人工放行")
    job2 = run_alpha(app, client, "次轮")
    qid2 = quarantine_id_of(app, job2, "A-004")
    assert qid2 is not None
    with app.app_context():
        with pytest.raises(ValueError, match="72"):
            release_to_main(job2, qid2, "重复放行")
    assert count(
        app,
        "SELECT COUNT(*) c FROM quarantine_records WHERE job_id = ? AND sku = 'A-004'",
        (job2,),
    ) == 1


def test_release_allowed_after_72h_window(app, client):
    """同编码最近一次放行已超过 72 小时 → 可再次放行。"""
    job_id = run_alpha(app, client, "冷却期外")
    qid = quarantine_id_of(app, job_id, "A-004")
    with app.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO release_logs (job_id, item_key, sku, title, remark, released_at)"
            " VALUES (?, 'k', 'A-004', '旧题', '历史放行', datetime('now', '-73 hours'))",
            (job_id,),
        )
        db.commit()
        result = release_to_main(job_id, qid, "超过冷却期再次放行")
    assert result["sku"] == "A-004"
    assert count(
        app,
        "SELECT COUNT(*) c FROM crawl_records WHERE job_id = ? AND sku = 'A-004'",
        (job_id,),
    ) == 1
