from app.db import get_db
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


def test_list_filters_quarantined_and_failed(app, client):
    """列表支持「仅含隔离」「仅失败」筛选，且卡片展示最近新写入/跳过/隔离。"""
    login(client)
    create_job(client, "甲-部分隔离", "/mock/catalog/alpha")
    create_job(client, "乙-全部失败", "/mock/catalog/gamma")
    create_job(client, "丙-全部合法", "/mock/catalog/beta")
    with app.app_context():
        db = get_db()
        ids = {
            row["name"]: row["id"]
            for row in db.execute("SELECT id, name FROM crawl_jobs")
        }
        for jid in ids.values():
            run_job(jid)

    body = client.get("/").get_data(as_text=True)
    assert "甲-部分隔离" in body
    assert "乙-全部失败" in body
    assert "丙-全部合法" in body
    # 卡片展示最近一轮统计：alpha 新写入 2、跳过 1、隔离 4
    assert "最近新写入" in body

    body = client.get("/?filter=quarantined").get_data(as_text=True)
    assert "甲-部分隔离" in body
    assert "乙-全部失败" in body  # 失败任务的非法条目也在隔离库
    assert "丙-全部合法" not in body

    body = client.get("/?filter=failed").get_data(as_text=True)
    assert "乙-全部失败" in body
    assert "甲-部分隔离" not in body
    assert "丙-全部合法" not in body
