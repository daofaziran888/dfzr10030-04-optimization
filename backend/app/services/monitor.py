"""采集监控 分析看板服务：汇总指标、运行分析并生成模拟结果。

主机规则索引及冲突清单
----------------------
顺着采集规则服务链路排查时，监控面板服务此前沿自己的链路临时生成视图，
与采集规则服务各算各的（服务错位）。现改为读取同一份持久化快照：
主机规则索引及冲突清单由共享服务按批次重算并落库，监控面板只做读取、
趋势归并与待复核台账登记，网页采集规则侧可按批次回查同一份数据。
"""
from __future__ import annotations

import random
from typing import Any

from app.services.host_index import host_index_service
from app.store import store

MODULE = "monitor"
REQUIRED_FIELDS = ["面板编号", "采集源总数", "今日采集量"]
STATUS_ORDER = ["正常", "预警", "告警"]
ACTION_RULES = {"查看详情": "正常"}
NEGATIVE_ACTIONS = []


class MonitorService:
    def list_results(self) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        results: list[dict] = []
        for row in rows:
            d = dict(row)
            d["指标值"] = round(random.uniform(0.65, 0.98), 3)
            d["对比基准"] = round(random.uniform(0.60, 0.92), 3)
            d["差异"] = round(d["指标值"] - d["对比基准"], 3)
            results.append(d)
        return results

    def run_analysis(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        count = int(params.get("样本范围", params.get("并行数量", "6")))
        results: list[dict] = []
        for i in range(count):
            results.append({
                "id": i + 1,
                "分组": f"分组{(i%3)+1}",
                "指标值": round(random.uniform(0.62, 1.02), 3),
                "对比基准": round(random.uniform(0.58, 0.95), 3),
                "差异": round(random.uniform(-0.2, 0.3), 3),
            })
        return results

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    # ---- 主机规则索引及冲突清单（与采集规则服务同一份持久化快照） ----

    def host_index_snapshot(self, *, host: str | None = None, batch_no: str | None = None) -> dict[str, Any]:
        """读取主机规则索引：监控面板通过自己的链路取到同一份快照。"""
        items, total, batch = host_index_service.list_entries(
            host=host, batch_no=batch_no, page=1, size=500)
        return {"items": items, "total": total, "批次": batch}

    def host_conflicts(self, *, batch_no: str | None = None) -> dict[str, Any]:
        """读取编码冲突清单：与采集规则服务看到的批次一致。"""
        items, batch = host_index_service.list_conflicts(batch_no=batch_no)
        return {"items": items, "批次": batch}

    def host_trends(self, *, host: str | None = None, batch_no: str | None = None) -> dict[str, Any]:
        """失败抓取趋势清单：把失败与乱码按主机和编码归并。"""
        items, batch = host_index_service.list_trends(batch_no=batch_no, host=host)
        return {"items": items, "批次": batch}

    def review_ledger(self, *, status: str | None = None, batch_no: str | None = None) -> list[dict[str, Any]]:
        """待复核台账：编码冲突随批次落账，供监控值班复核。"""
        return host_index_service.list_ledger(status=status, batch_no=batch_no)

    def review_ledger_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        return host_index_service.review_ledger(entry_id, action)
