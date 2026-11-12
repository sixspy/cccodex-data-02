# cc-data-lab

CC_Codex 二期（26.11）**数据工程**主线基线：**采集任务控制台**（Flask 后端 + HTMX 前端页 + 站内 Mock 目录）。

## 领域

- **所属领域**：数据工程  
- **子方向**：数据采集、爬虫与 RPA  

## 技术栈

- Python 3.12+、Flask 3、SQLite  
- HTMX（CDN）+ Jinja 模板  
- pytest  

## 本地运行

```powershell
cd claude-workspace\cc-data-lab
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest
python run.py
```

浏览器打开 http://127.0.0.1:5590 ，登录 **admin / 123456**。

流程：创建任务 → 选种子 `/mock/catalog/alpha`（部分非法）、`beta`（全合法）、`gamma`（全非法）或 `delta`（编码重复）→ 详情页「运行采集」→ 查看正式库 / 隔离库两表 → 隔离条目填备注申请放行。

## 采集校验与隔离规则（仅服务端裁决）

解析后逐条校验，**合法入正式库，非法入隔离库**，两库在详情页分开展示。非法情形（按序裁决，只记首个命中原因）：

1. **编码为空**；
2. **编码格式不符**：须为所属目录声明的「字头 + 短横线 + 三位数字」（如 alpha 目录声明字头 `A`，合法编码形如 `A-001`）；
3. **标题不足四字**：标题去除全部空白字符后不足 4 字。

落库约束：

- **同任务内编码唯一**（正式库、隔离库分别唯一，空编码不参与）；
- **隔离与正式库不得同编码共存**：非法条目的编码若已在任一库占位，则记为跳过；合法条目的编码若被隔离条目占用，同样跳过，留待人工放行裁决；
- **全部非法且新写入为零 → 任务失败**：本次运行没有任何条目写入正式库、且解析出的条目全部不合法时，任务置为 `failed` 并在详情页给出提示（重跑时非法条目已在隔离库、新写入仍为零，依旧失败）；部分合法则任务成功，详情页两表并列并显示新写入与隔离数。

## 人工放行规则

隔离库条目可**单条申请放行**入正式库：

- 须填写**非空备注**（纯空白视为空）；
- **同编码 72 小时内已有放行记录的不得再次放行**（按放行留痕时间判定，空编码不参与此限制）；
- 正式库已存在同编码/同条目时拒绝放行；
- 放行成功后**从隔离库移除**，写入正式库，并在详情页「放行留痕」中记录编码、标题、备注与放行时间；任一规则不满足则整体回滚，隔离条目保留。

## 并发规则

- 同一任务**运行中再次触发须拒绝**（原子占位：仅 `draft` / `failed` 状态可启动，`running` / `done` 一律拒绝）；失败任务可重跑。

## 列表与筛选

- 任务列表卡片展示每个任务**最近一次运行的新写入 / 跳过 / 隔离**计数及当前**待放行**隔离条数；
- 支持筛选：**仅含隔离**（当前有待放行隔离条目的任务）、**仅失败**（`failed` 状态任务）。

## 自动化测试

`pytest` 共 12 条用例，覆盖：非法样本不入正式库、全部非法任务失败（含重跑）、部分合法成功、空备注拒放行、72 小时内重放行拒绝、超 72 小时可放行、运行中拒绝二次触发、列表筛选结果、放行后隔离侧消失且正式库留痕、同任务内编码唯一等。

## Docker 一键启动（推荐用于快照前验收）

需已打开 **Docker Desktop**：

```powershell
cd claude-workspace\cc-data-lab
docker compose up -d --build
docker compose ps
```

- 页面：http://127.0.0.1:5590/login  
- Mock：http://127.0.0.1:5590/mock/catalog/alpha  
- 停止：`docker compose down`（保留库卷）· 清卷：`docker compose down -v`

`docker compose ps` 中 `STATUS` 含 **healthy** 表示服务可访问。线下表「环境可复现等级」可填 **已容器化，可一键起环境**。

## 前后端说明

| 层 | 说明 |
|----|------|
| 后端 | `app/` 路由、任务状态机、同步 runner、SQLite |
| 前端 | `templates/` + `static/`，浏览器可点操作 |
| Mock 源站 | `/mock/catalog/<id>` HTML，无需外网 |

## 初始快照

在首次 Claude 单轮跑题前 commit + push 本树（不含 `.venv/`、`instance/*.db`）。后续题目在同 repo 上叠加调度、RPA 步骤、增量水位等能力。

## 基线 vs 跑题目录

| 路径 | 角色 |
|------|------|
| `claude-workspace/cc-data-lab`（本目录） | **基线**：改功能、docker 验收 |
| `ccproject/cc-data-lab/data-XX` | **单题**：复制基线后挂容器、出快照 |

复制：`..\scripts\Copy-BaselineToQuestion.ps1 -QuestionId data-01`

## 跑题 Harness

见 `CCcodex/docs/ClaudeCode_Windows使用说明.md`（镜像 2.0）。容器挂载 **ccproject 下该题目录**，不是本基线路径。
