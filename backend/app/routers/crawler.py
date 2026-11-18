"""网页采集规则接口：维护采集规则，覆盖提交测试、发布规则、停用规则等动作。"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.schemas import ActionPayload, ActionResult, EntryPayload, PageResult
from app.services.crawler import CrawlerService
from app.services.host_index import host_index_service

router = APIRouter(prefix="/api/crawler", tags=["网页采集规则"])

service = CrawlerService()

LIST_FIELDS = ["规则编号", "目标网址", "页面选择器", "正文选择器", "翻页参数", "抓取频率", "字符编码", "去重策略"]
STATUSES = ["草稿", "测试中", "已发布", "已停用"]


def query_filters(request: Request) -> dict[str, str]:
    """只接受当前模块声明过的字段，忽略分页等保留参数。"""
    return {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in LIST_FIELDS and value.strip()
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按规则编号检索"),
    status: str | None = Query(default=None, description="草稿、测试中、已发布、已停用"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """按页面字段、规则编号关键字与状态过滤网页采集规则列表。"""
    items, total = service.list_entries(
        filters=query_filters(request), keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/host-index")
def list_host_index(
    host: str | None = Query(default=None, description="按目标主机检索"),
    rule: str | None = Query(default=None, description="按规则编号检索"),
    encoding: str | None = Query(default=None, description="按字符编码筛选"),
    conflict_only: bool = Query(default=False, description="只看编码冲突的主机"),
    batch: str | None = Query(default=None, description="批次号，缺省取当前批次"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
) -> dict:
    """主机规则索引：同一主机只占一个索引项，保留规则编号与当前编码。"""
    items, total, batch_info = host_index_service.list_entries(
        host=host, rule=rule, encoding=encoding, conflict_only=conflict_only,
        batch_no=batch, page=page, size=size)
    return {"items": items, "total": total, "page": page, "size": size, "批次": batch_info}


@router.get("/host-index/conflicts")
def list_host_conflicts(
    batch: str | None = Query(default=None, description="批次号，缺省取当前批次"),
    host: str | None = Query(default=None, description="按目标主机检索"),
) -> dict:
    """编码冲突清单：同一主机出现多个编码时保留全部编码、涉及规则与样本证据。"""
    items, batch_info = host_index_service.list_conflicts(batch_no=batch, host=host)
    return {"items": items, "批次": batch_info}


@router.get("/host-index/batches")
def list_host_index_batches() -> dict:
    """批次历史：以批次版本为准重算，历史批次保留，可按批次回查。"""
    return {"items": host_index_service.list_batches()}


@router.get("/host-index/detail")
def host_index_detail(
    host: str = Query(..., description="目标主机"),
    batch: str | None = Query(default=None, description="批次号，缺省取当前批次"),
) -> dict:
    """展开单个主机索引项：规则编号、字符编码与最近抓取样本。"""
    entry, batch_info = host_index_service.get_host_detail(host, batch_no=batch)
    if entry is None:
        batch_no = batch_info["批次号"] if batch_info else "-"
        raise HTTPException(status_code=404, detail=f"主机 {host} 在批次 {batch_no} 中没有索引项")
    return {"item": entry, "批次": batch_info}


@router.post("/host-index/rebuild", response_model=ActionResult)
def rebuild_host_index(payload: dict[str, object] | None = None) -> ActionResult:
    """重算主机规则索引及冲突清单；相同输入（或同一请求键）再提交不多写。"""
    key = ""
    if payload:
        key = str(payload.get("请求键") or "").strip()
    batch, created = host_index_service.rebuild(trigger="采集规则服务", request_key=key or None)
    if created:
        message = f"主机规则索引已重算，当前批次 {batch['批次号']}（主机 {batch['主机数']} 个，冲突 {batch['冲突数']} 条）"
    else:
        message = f"相同输入的批次 {batch['批次号']} 已存在，本次未重复写入"
    return ActionResult(ok=True, message=message, entry=batch)


@router.get("/export")
def export_entries(
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> StreamingResponse:
    """下载当前筛选条件下的 UTF-8 CSV；必须声明在 /{entry_id} 之前。"""
    items, _ = service.list_entries(
        filters=query_filters(request), keyword=keyword, status=status, page=1, size=1000000)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["id", *LIST_FIELDS, "status"])
    for item in items:
        row = []
        for value in [item.get("id"), *(item.get(field, "") for field in LIST_FIELDS), item.get("status", "")]:
            text = "" if value is None else str(value)
            row.append("'" + text if text.startswith(("=", "+", "-", "@")) else text)
        writer.writerow(row)
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="crawler.csv"'})


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条采集规则明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"采集规则 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: dict[str, object]) -> ActionResult:
    """登记一条采集规则，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="采集规则已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: ActionPayload) -> ActionResult:
    """对单条采集规则执行提交测试、发布规则、停用规则；不允许的动作会被拦下并说明原因。"""
    entry, message = service.run_action(entry_id, payload.action.strip())
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
