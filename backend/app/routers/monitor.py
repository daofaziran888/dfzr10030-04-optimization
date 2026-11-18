"""采集监控 分析看板接口：汇总指标、参数运行与结果导出。"""
from __future__ import annotations

import csv
import io
import random
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.schemas import ActionPayload, ActionResult, EntryPayload
from app.services.monitor import MonitorService

router = APIRouter(prefix="/api/monitor", tags=["采集监控"])
service = MonitorService()
LIST_FIELDS = ["面板编号", "采集源总数", "今日采集量", "成功率", "平均延迟", "失败重试", "异常告警", "更新时间"]
STATUSES = ["正常", "预警", "告警"]


def csv_cell(value: Any) -> str:
    text = str(value) if value is not None else ""
    if text and text[0] in "=+-@":
        text = "'" + text
    return '"' + text.replace('"', '""') + '"'


@router.get("/summary")
def get_summary() -> dict[str, Any]:
    return {"metrics": [
        {"label": "覆盖数据源", "value": random.randint(12, 45), "trend": random.randint(-12, 25)},
        {"label": "最新指标值", "value": round(random.uniform(0.72, 0.99), 3), "trend": random.randint(-8, 15)},
        {"label": "异常记录", "value": random.randint(0, 8), "trend": -random.randint(1, 10)},
    ]}


@router.get("")
def list_results() -> dict[str, Any]:
    return {"items": service.list_results()}


@router.post("/run")
def run_analysis(payload: EntryPayload) -> dict[str, Any]:
    results = service.run_analysis(payload.values)
    return {"items": results}


@router.get("/host-index")
def monitor_host_index(
    host: str | None = Query(default=None, description="按目标主机检索"),
    batch: str | None = Query(default=None, description="批次号，缺省取当前批次"),
) -> dict[str, Any]:
    """主机规则索引：监控面板通过自己的链路读取与采集规则服务同一份快照。"""
    return service.host_index_snapshot(host=host, batch_no=batch)


@router.get("/host-index/conflicts")
def monitor_host_conflicts(
    batch: str | None = Query(default=None, description="批次号，缺省取当前批次"),
) -> dict[str, Any]:
    """编码冲突清单：与采集规则服务读到的批次一致。"""
    return service.host_conflicts(batch_no=batch)


@router.get("/host-trends")
def monitor_host_trends(
    host: str | None = Query(default=None, description="按目标主机检索"),
    batch: str | None = Query(default=None, description="批次号，缺省取当前批次"),
) -> dict[str, Any]:
    """失败抓取趋势清单：按主机和编码归并失败与乱码。"""
    return service.host_trends(host=host, batch_no=batch)


@router.get("/review-ledger")
def monitor_review_ledger(
    status: str | None = Query(default=None, description="待复核、已复核"),
    batch: str | None = Query(default=None, description="按批次号回查"),
) -> dict[str, Any]:
    """待复核台账：编码冲突随批次落账，网页采集规则侧可按批次回查。"""
    return {"items": service.review_ledger(status=status, batch_no=batch)}


@router.post("/review-ledger/{entry_id}/actions", response_model=ActionResult)
def review_ledger_action(entry_id: int, payload: ActionPayload) -> ActionResult:
    """对待复核台账执行标记已复核、重新打开；状态同步回冲突清单。"""
    entry, message = service.review_ledger_action(entry_id, payload.action.strip())
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> StreamingResponse:
    items = service.list_results()
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    all_keys = ["id"]
    if items:
        all_keys = list(items[0].keys())
    writer.writerow(all_keys)
    for item in items:
        writer.writerow([csv_cell(item.get(k, "")) for k in all_keys])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=monitor.csv"})


@router.get("/{entry_id}")
def get_entry(entry_id: int) -> dict:
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"监控面板 {entry_id} 不存在")
    return entry
