"""采集条目服务端校验：合法入正式库，非法入隔离库。仅服务端裁决。"""

import re

MIN_TITLE_LEN = 4

REASON_EMPTY_CODE = "编码为空"
REASON_BAD_CODE = "编码格式不符"
REASON_SHORT_TITLE = "标题不足四字"


def validate_item(item: dict, declared_prefix: str) -> str | None:
    """返回 None 表示合法，否则返回非法原因（中文，供隔离库与页面展示）。

    非法情形（按优先级裁决，只报首个命中的原因）：
    1. 编码为空；
    2. 编码不符合所属目录声明的「字头 + 短横线 + 三位数字」格式；
    3. 标题去空白后不足四字。
    """
    code = (item.get("sku") or "").strip()
    if not code:
        return REASON_EMPTY_CODE
    if not re.fullmatch(rf"{re.escape(declared_prefix)}-\d{{3}}", code):
        return REASON_BAD_CODE
    title_norm = re.sub(r"\s+", "", item.get("title") or "")
    if len(title_norm) < MIN_TITLE_LEN:
        return REASON_SHORT_TITLE
    return None
