from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.db import get_db
from app.routes.auth import login_required
from app.services.mock_catalog import CATALOGS
from app.services.release import release_to_main
from app.services.runner import JobConflictError, run_job

bp = Blueprint("jobs", __name__)

FILTERS = {
    "": "全部",
    "quarantined": "仅含隔离",
    "failed": "仅失败",
}


@bp.route("/")
@login_required
def list_jobs():
    filter_kind = request.args.get("filter", "")
    if filter_kind not in FILTERS:
        filter_kind = ""
    db = get_db()
    jobs = db.execute(
        "SELECT * FROM crawl_jobs ORDER BY id DESC"
    ).fetchall()
    quarantine_counts = {
        row["job_id"]: row["c"]
        for row in db.execute(
            "SELECT job_id, COUNT(*) AS c FROM quarantine_records GROUP BY job_id"
        )
    }
    if filter_kind == "quarantined":
        jobs = [j for j in jobs if quarantine_counts.get(j["id"], 0) > 0]
    elif filter_kind == "failed":
        jobs = [j for j in jobs if j["status"] == "failed"]
    return render_template(
        "jobs_list.html",
        jobs=jobs,
        quarantine_counts=quarantine_counts,
        seeds=sorted(CATALOGS.keys()),
        filters=FILTERS,
        active_filter=filter_kind,
    )


@bp.post("/jobs")
@login_required
def create_job():
    name = request.form.get("name", "").strip()
    seed = request.form.get("seed_path", "").strip()
    if not name or not seed:
        flash("请填写任务名与种子路径", "error")
        return redirect(url_for("jobs.list_jobs"))
    if seed not in CATALOGS:
        flash("种子路径必须是已注册的 mock 目录", "error")
        return redirect(url_for("jobs.list_jobs"))
    db = get_db()
    db.execute(
        "INSERT INTO crawl_jobs (name, seed_path, status) VALUES (?, ?, 'draft')",
        (name, seed),
    )
    db.commit()
    flash("任务已创建", "ok")
    return redirect(url_for("jobs.list_jobs"))


@bp.post("/jobs/<int:job_id>/run")
@login_required
def run_job_view(job_id: int):
    try:
        summary = run_job(job_id)
    except (JobConflictError, ValueError) as e:
        flash(str(e), "error")
        return redirect(url_for("jobs.detail", job_id=job_id))
    except Exception as e:
        flash(f"运行失败: {e}", "error")
        return redirect(url_for("jobs.detail", job_id=job_id))
    if summary["status"] == "failed":
        flash(summary["message"], "error")
    else:
        flash(
            f"运行完成：新写入 {summary['inserted']} 条，"
            f"跳过 {summary['skipped_dup']} 条，隔离 {summary['quarantined']} 条",
            "ok",
        )
    return redirect(url_for("jobs.detail", job_id=job_id))


@bp.post("/jobs/<int:job_id>/quarantine/<int:quarantine_id>/release")
@login_required
def release_quarantine(job_id: int, quarantine_id: int):
    remark = request.form.get("remark", "")
    try:
        result = release_to_main(job_id, quarantine_id, remark)
        flash(f"已放行 {result['sku'] or '(无编码)'}《{result['title']}》入正式库", "ok")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("jobs.detail", job_id=job_id))


@bp.get("/jobs/<int:job_id>")
@login_required
def detail(job_id: int):
    db = get_db()
    job = db.execute("SELECT * FROM crawl_jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        flash("任务不存在", "error")
        return redirect(url_for("jobs.list_jobs"))
    records = db.execute(
        "SELECT * FROM crawl_records WHERE job_id = ? ORDER BY id",
        (job_id,),
    ).fetchall()
    quarantined = db.execute(
        "SELECT * FROM quarantine_records WHERE job_id = ? ORDER BY id",
        (job_id,),
    ).fetchall()
    releases = db.execute(
        "SELECT * FROM release_logs WHERE job_id = ? ORDER BY id DESC",
        (job_id,),
    ).fetchall()
    return render_template(
        "job_detail.html",
        job=job,
        records=records,
        quarantined=quarantined,
        releases=releases,
    )
