# 多源数据采集与RPA自动化平台

面向网页抓取、API接入、增量采集、RPA流程编排、数据校验与采集监控的数据工程平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 数据源配置 | `datasource` | 数据源 | 源端编号、连接类型、接入地址 |
| 网页采集规则 | `crawler` | 采集规则 | 规则编号、目标网址、页面选择器 |
| API接入管理 | `apiclient` | API客户端 | 客户端编号、接口名称、请求方法 |
| 增量采集 | `incremental` | 增量游标 | 游标编号、来源标识、增量字段 |
| RPA任务编排 | `robot_task` | RPA任务 | 任务编号、任务名称、页面定位器 |
| 数据接入通道 | `ingestion` | 接入通道 | 通道编号、通道名称、输入格式 |
| 格式解析器 | `parser` | 解析配置 | 解析编号、输入格式、输出格式 |
| 采集结果校验 | `validator` | 校验规则 | 规则编号、校验字段、校验类型 |
| 采集去重 | `dedup` | 去重策略 | 策略编号、输入来源、去重键 |
| 采集调度 | `schedule` | 调度计划 | 计划编号、关联任务、调度周期 |
| 采集监控 | `monitor` | 监控面板 | 面板编号、采集源总数、今日采集量 |
| 采集日志 | `log_viewer` | 日志条目 | 日志编号、关联任务、日志级别 |
| 凭证管理 | `auth` | 认证凭证 | 凭证编号、凭证类型、关联数据源 |
| 采集转换管道 | `transform` | 转换节点 | 节点编号、输入来源、输出目标 |
| 数据流转编排 | `flow` | 流转管道 | 管道编号、管道名称、起始节点 |
| 数据血缘追踪 | `lineage` | 血缘关系 | 关系编号、上游节点、下游节点 |
| 采集报告 | `report` | 采集报告 | 报告编号、采集源、统计周期 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 主机规则索引及冲突清单

网页采集规则不再逐条比较目标网址与字符编码，而是由 `app/services/host_index.py`
按目标主机归并采集规则、结合最近抓取样本识别编码冲突，生成持久化快照：

- 同一主机只占一个索引项，保留规则编号与当前编码；同一主机出现多个编码时进入
  冲突清单，保留全部冲突编码、涉及规则与样本证据，乱码排查可回溯到具体规则和
  最近抓取样本。
- 快照以批次版本为准重算，历史批次保留可按批次回查；重建按请求键（缺省为内容
  指纹）幂等，相同输入再提交不多写，并发重建只落一个批次。
- 采集规则服务与监控面板服务读写同一份快照：规则登记/状态动作会触发重算，
  监控面板通过自己的链路读到同一批次，并把失败抓取按主机+编码归入趋势清单、
  把编码冲突落到待复核台账。

主要接口：

| 链路 | 接口 | 说明 |
| --- | --- | --- |
| 采集规则 | `GET /api/crawler/host-index` | 按主机/规则编号/编码检索，可只看冲突、按批次回查 |
| 采集规则 | `GET /api/crawler/host-index/detail?host=` | 展开主机索引项：规则编号、编码、最近抓取样本 |
| 采集规则 | `GET /api/crawler/host-index/conflicts` | 编码冲突清单 |
| 采集规则 | `GET /api/crawler/host-index/batches` | 批次历史 |
| 采集规则 | `POST /api/crawler/host-index/rebuild` | 重算索引（幂等） |
| 监控面板 | `GET /api/monitor/host-index` | 同一份主机规则索引快照 |
| 监控面板 | `GET /api/monitor/host-trends` | 失败抓取趋势清单（按主机+编码） |
| 监控面板 | `GET /api/monitor/review-ledger` | 待复核台账 |
| 监控面板 | `POST /api/monitor/review-ledger/{id}/actions` | 标记已复核 / 重新打开 |

领域：数据工程
子方向：数据采集、爬虫与RPA
