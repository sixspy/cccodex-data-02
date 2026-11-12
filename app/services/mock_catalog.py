"""站内 mock 目录页，模拟可采集列表（无外网依赖）。

每个目录声明自己的编码字头（prefix），条目编码须满足
``<字头>-<三位数字>`` 才算合法，校验规则见 app.services.validate。
"""

from html import escape

CATALOGS = {
    "/mock/catalog/alpha": {
        "prefix": "A",
        "items": [
            {"sku": "A-001", "title": "市政管线测绘记录表"},
            {"sku": "A-002", "title": "排水井巡查台账"},
            {"sku": "A-003", "title": "排水井巡查台账"},  # 标题重复 → 去重跳过
            # 以下为本目录声明字头 A 下的不合法样本
            {"sku": "", "title": "无名巡检补录条目"},        # 编码为空
            {"sku": "X-009", "title": "字头不符的样本记录"},  # 字头不符
            {"sku": "A-09", "title": "位数不足的样本记录"},   # 非三位数字
            {"sku": "A-004", "title": "短题"},              # 标题不足四字
        ],
    },
    "/mock/catalog/beta": {
        "prefix": "B",
        "items": [
            {"sku": "B-101", "title": "泵站运行日报"},
            {"sku": "B-102", "title": "雨污分流抽检单"},
        ],
    },
    "/mock/catalog/gamma": {
        "prefix": "G",
        "items": [
            # 全部不合法：用于演示「全部非法且新写入为零 → 任务失败」
            {"sku": "G-1", "title": "编码位数不足的样本"},
            {"sku": "", "title": "缺少编码的样本条目"},
            {"sku": "G-002", "title": "短"},
        ],
    },
    "/mock/catalog/delta": {
        "prefix": "D",
        "items": [
            {"sku": "D-001", "title": "闸阀年检记录表"},
            {"sku": "D-001", "title": "同编码另一标题"},  # 同任务内编码重复 → 跳过
            {"sku": "D-001", "title": "短"},             # 非法且编码已在正式库 → 跳过
            {"sku": "D-002", "title": "漏"},             # 标题不足四字 → 隔离
        ],
    },
}


def get_catalog(path: str) -> dict | None:
    return CATALOGS.get(path)


def render_catalog_page(path: str) -> str:
    catalog = CATALOGS.get(path)
    if catalog is None:
        return _not_found(path)
    rows = "".join(
        f"<li data-sku='{escape(it['sku'])}'>{escape(it['title'])}</li>"
        for it in catalog["items"]
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>Mock 目录 {escape(path)}</title></head>
<body>
<h1>采集演练目录</h1>
<p class="seed">{escape(path)}</p>
<p class="prefix">编码字头：<code>{escape(catalog["prefix"])}</code>（格式 {escape(catalog["prefix"])}-NNN）</p>
<ul id="items">{rows}</ul>
</body></html>"""


def _not_found(path: str) -> str:
    return f"<html><body><h1>404</h1><p>{escape(path)}</p></body></html>", 404


def parse_catalog_html(html: str, seed_path: str) -> list[dict]:
    """极简解析：从 &lt;li data-sku&gt; 抽条目（基线够用，后续题可换解析器）。

    编码允许为空串（data-sku=''），是否合法由服务端校验裁决。
    """
    import re

    pattern = re.compile(
        r"<li\s+data-sku='([^']*)'\s*>([^<]+)</li>",
        re.IGNORECASE,
    )
    out = []
    for sku, title in pattern.findall(html):
        out.append({"sku": sku, "title": title.strip(), "seed_path": seed_path})
    return out
