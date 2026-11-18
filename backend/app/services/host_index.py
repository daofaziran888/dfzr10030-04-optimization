"""主机规则索引及冲突清单：按目标主机归并采集规则、识别编码冲突的共享快照服务。

背景与取舍
----------
旧逻辑每次查询都逐条比较目标网址与字符编码：同一站点的多个栏目被拆成数十条
规则，排查乱码时只能逐条打开目标网址，真实乱码来源常被页面定位掩盖。围绕
「以目标主机和编码建立可检索的采集规则索引」有两种取舍：

- 索引前置保持主机唯一：同一主机只占一个索引项，浏览更集中；同主机出现多个
  编码时不拆条目，编码信息通过冲突清单补齐（本实现采用这一口径）；
- 按规则拆分同主机索引：逐条标出编码、规则完整前置，但同一主机会出现多个
  定位入口，主机维度被拆散。

两种口径下主机规则索引及冲突清单的版本会不同，本实现以批次版本为准重算，
历史批次保留可查（历史兼容）。无论哪种口径，完整结果都必须让任何乱码排查
能回到具体规则和抓取样本：主机索引项保留规则编号与当前编码，冲突清单保留
全部冲突编码、涉及规则与样本证据。

一致性约定
----------
- 采集规则服务与监控面板服务读写同一份持久化快照，避免两条链路各算各的错位；
- 重建按请求键（缺省为内容指纹）幂等：相同输入再提交不多写；
- 并发重建在锁内二次检查，竞态更新只落一个批次结果。
"""
from __future__ import annotations

import hashlib
import threading
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from app.store import store

MODULE_RULES = "crawler"
MODULE_SAMPLES = "fetch_sample"
TABLE_BATCH = "host_index_batch"
TABLE_ENTRY = "host_index_entry"
TABLE_CONFLICT = "host_index_conflict"
TABLE_TREND = "monitor_trend"
TABLE_LEDGER = "review_ledger"

ENCODING_ALIASES = {
    "utf8": "utf-8",
    "unicode": "utf-8",
    "gb-2312": "gb2312",
    "big5-hkscs": "big5",
}
UNKNOWN_ENCODING = "未声明"
UNKNOWN_HOST = "（未识别主机）"
SAMPLE_SNAPSHOT_LIMIT = 5
LEDGER_ACTIONS = {"标记已复核": "已复核", "重新打开": "待复核"}


def normalize_host(url: object) -> str:
    """从目标网址提取目标主机；缺协议时补 https://，无法识别时返回空串。"""
    text = str(url or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    parsed = urlparse(text)
    host = (parsed.netloc or "").strip().lower()
    if not host:
        host = parsed.path.split("/")[0].strip().lower()
    return host


def normalize_encoding(value: object) -> str:
    """统一编码写法（大小写与常见别名），空值记为未声明。"""
    text = str(value or "").strip().lower().replace("_", "-")
    if not text:
        return UNKNOWN_ENCODING
    return ENCODING_ALIASES.get(text, text)


def _next_id(rows: list[dict[str, Any]]) -> int:
    return max((int(row.get("id", 0)) for row in rows), default=0) + 1


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class HostIndexService:
    """主机规则索引及冲突清单的构建与查询；采集规则服务、监控面板服务共用。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    # ---------------- 构建 ----------------

    def _fingerprint(self, rules: list[dict], samples: list[dict]) -> str:
        """内容指纹：索引输入（规则网址/编码/状态 + 抓取样本）相同则结果相同。"""
        digest = hashlib.sha1()
        for row in sorted(rules, key=lambda r: str(r.get("规则编号", ""))):
            digest.update("|".join(
                str(row.get(key, "")) for key in ("规则编号", "目标网址", "字符编码", "status")
            ).encode("utf-8"))
            digest.update(b"\x00")
        for row in sorted(samples, key=lambda r: str(r.get("样本编号", ""))):
            digest.update("|".join(
                str(row.get(key, "")) for key in ("样本编号", "规则编号", "抓取结果", "检测编码", "乱码标记")
            ).encode("utf-8"))
            digest.update(b"\x00")
        return "fp:" + digest.hexdigest()

    def rebuild(self, *, trigger: str = "采集规则服务", request_key: str | None = None) -> tuple[dict[str, Any], bool]:
        """按当前采集规则与最近抓取样本重算索引快照，返回 (批次, 是否新建)。

        幂等：请求键（缺省为内容指纹）相同的提交直接返回已有批次，不多写；
        竞态：并发重建在锁内二次检查，只落一个结果。
        """
        rules = [dict(row) for row in store.rows(MODULE_RULES)]
        samples = [dict(row) for row in store.rows(MODULE_SAMPLES)]
        key = (request_key or "").strip()
        fingerprint = f"req:{key}" if key else self._fingerprint(rules, samples)
        for batch in store.rows(TABLE_BATCH):
            if batch.get("请求键") == fingerprint:
                return batch, False
        with self._lock:
            for batch in store.rows(TABLE_BATCH):
                if batch.get("请求键") == fingerprint:
                    return batch, False
            batches = store.rows(TABLE_BATCH)
            previous = self._current_batch()
            previous_trends = [
                row for row in store.rows(TABLE_TREND)
                if previous and row.get("批次号") == previous.get("批次号")
            ]
            seq = len(batches) + 1
            batch_no = f"IDX-{datetime.now():%Y%m%d}-{seq:04d}"
            entries, conflicts, trends, ledger = self._build_rows(rules, samples, batch_no, previous_trends)
            for batch in batches:
                batch["状态"] = "历史"
            batch = {
                "id": _next_id(batches),
                "批次号": batch_no,
                "版本": seq,
                "状态": "当前",
                "规则数": len(rules),
                "主机数": len(entries),
                "冲突数": len(conflicts),
                "样本数": len(samples),
                "请求键": fingerprint,
                "触发来源": trigger,
                "生成时间": _now(),
            }
            batches.append(batch)
            self._append_rows(TABLE_ENTRY, entries)
            self._append_rows(TABLE_CONFLICT, conflicts)
            self._append_rows(TABLE_TREND, trends)
            self._append_rows(TABLE_LEDGER, ledger)
            return batch, True

    def _append_rows(self, table: str, rows: list[dict[str, Any]]) -> None:
        target = store.rows(table)
        next_id = _next_id(target)
        for offset, row in enumerate(rows):
            row["id"] = next_id + offset
            target.append(row)

    def _build_rows(
        self,
        rules: list[dict],
        samples: list[dict],
        batch_no: str,
        previous_trends: list[dict],
    ) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
        samples_by_rule: dict[str, list[dict]] = {}
        for sample in samples:
            samples_by_rule.setdefault(str(sample.get("规则编号", "")), []).append(sample)
        hosts: dict[str, list[dict]] = {}
        for rule in rules:
            host = normalize_host(rule.get("目标网址")) or UNKNOWN_HOST
            hosts.setdefault(host, []).append(rule)

        entries: list[dict] = []
        conflicts: list[dict] = []
        trends: list[dict] = []
        ledger: list[dict] = []
        previous_map = {
            (str(row.get("主机", "")), str(row.get("字符编码", ""))): row for row in previous_trends
        }
        for host in sorted(hosts):
            host_rules = sorted(hosts[host], key=lambda r: str(r.get("规则编号", "")))
            rule_items = [{
                "规则编号": str(rule.get("规则编号", "")),
                "字符编码": normalize_encoding(rule.get("字符编码")),
                "状态": str(rule.get("status", "")),
                "目标网址": str(rule.get("目标网址", "")),
            } for rule in host_rules]
            encodings = sorted({item["字符编码"] for item in rule_items})
            host_samples = [
                sample for item in rule_items
                for sample in samples_by_rule.get(item["规则编号"], [])
            ]
            host_samples.sort(key=lambda s: str(s.get("抓取时间", "")), reverse=True)
            success = sum(1 for s in host_samples if s.get("抓取结果") == "成功")
            failed = sum(1 for s in host_samples if s.get("抓取结果") == "失败")
            garbled = sum(1 for s in host_samples if s.get("乱码标记") == "是")
            is_conflict = len(encodings) > 1
            # 同一主机只占一个索引项：保留规则编号与当前编码，编码冲突进冲突清单。
            entries.append({
                "批次号": batch_no,
                "主机": host,
                "规则数": len(rule_items),
                "规则编号": [item["规则编号"] for item in rule_items],
                "当前编码": self._current_encoding(rule_items, host_samples),
                "编码列表": encodings,
                "是否冲突": is_conflict,
                "成功数": success,
                "失败数": failed,
                "乱码数": garbled,
                "最近抓取时间": str(host_samples[0].get("抓取时间", "")) if host_samples else "",
                "规则明细": rule_items,
                "样本快照": [self._sample_view(s) for s in host_samples[:SAMPLE_SNAPSHOT_LIMIT]],
            })
            if is_conflict:
                # 同一主机出现多个编码必须留下冲突记录，并保留可回溯的样本证据。
                evidence = [
                    self._sample_view(s) for s in host_samples
                    if s.get("乱码标记") == "是" or s.get("抓取结果") == "失败"
                ][:SAMPLE_SNAPSHOT_LIMIT]
                conflicts.append({
                    "批次号": batch_no,
                    "主机": host,
                    "冲突编码": encodings,
                    "涉及规则": rule_items,
                    "样本证据": evidence,
                    "状态": "待复核",
                })
                ledger.append({
                    "批次号": batch_no,
                    "主机": host,
                    "冲突编码": " / ".join(encodings),
                    "涉及规则数": len(rule_items),
                    "来源服务": "监控面板服务",
                    "状态": "待复核",
                    "登记时间": _now(),
                    "复核人": "",
                    "复核时间": "",
                })
            for encoding in encodings:
                rule_codes = {item["规则编号"] for item in rule_items if item["字符编码"] == encoding}
                subset = [s for s in host_samples if str(s.get("规则编号", "")) in rule_codes]
                ok = sum(1 for s in subset if s.get("抓取结果") == "成功")
                bad = sum(1 for s in subset if s.get("抓取结果") == "失败")
                gar = sum(1 for s in subset if s.get("乱码标记") == "是")
                previous_row = previous_map.get((host, encoding))
                if previous_row is None:
                    trend = "新增"
                else:
                    previous_bad = int(previous_row.get("失败数", 0)) + int(previous_row.get("乱码数", 0))
                    current_bad = bad + gar
                    trend = "上升" if current_bad > previous_bad else "下降" if current_bad < previous_bad else "持平"
                trends.append({
                    "批次号": batch_no,
                    "主机": host,
                    "字符编码": encoding,
                    "成功数": ok,
                    "失败数": bad,
                    "乱码数": gar,
                    "趋势": trend,
                })
        return entries, conflicts, trends, ledger

    @staticmethod
    def _sample_view(sample: dict) -> dict[str, str]:
        return {
            "样本编号": str(sample.get("样本编号", "")),
            "规则编号": str(sample.get("规则编号", "")),
            "抓取时间": str(sample.get("抓取时间", "")),
            "抓取结果": str(sample.get("抓取结果", "")),
            "检测编码": str(sample.get("检测编码", "")),
            "乱码标记": str(sample.get("乱码标记", "")),
            "内容摘要": str(sample.get("内容摘要", "")),
        }

    @staticmethod
    def _current_encoding(rule_items: list[dict], host_samples: list[dict]) -> str:
        """当前编码：全主机一致时取该编码；冲突时取最近抓取样本所属规则的编码。"""
        encodings = {item["字符编码"] for item in rule_items}
        if len(encodings) == 1:
            return rule_items[0]["字符编码"]
        if host_samples:
            latest_rule = str(host_samples[0].get("规则编号", ""))
            for item in rule_items:
                if item["规则编号"] == latest_rule:
                    return item["字符编码"]
        return rule_items[0]["字符编码"]

    # ---------------- 查询 ----------------

    def _current_batch(self) -> dict[str, Any] | None:
        for batch in store.rows(TABLE_BATCH):
            if batch.get("状态") == "当前":
                return batch
        return None

    def ensure_current(self) -> dict[str, Any]:
        """首次读取时兜底建一批，保证两条链路看到的都是持久化快照。"""
        batch = self._current_batch()
        if batch is None:
            batch, _ = self.rebuild(trigger="系统初始化")
        return batch

    def list_batches(self) -> list[dict[str, Any]]:
        self.ensure_current()
        return sorted(store.rows(TABLE_BATCH), key=lambda b: int(b.get("版本", 0)), reverse=True)

    def _resolve_batch(self, batch_no: str | None = None) -> dict[str, Any] | None:
        if batch_no:
            for batch in store.rows(TABLE_BATCH):
                if batch.get("批次号") == batch_no:
                    return batch
            return None
        return self.ensure_current()

    def list_entries(
        self,
        *,
        host: str | None = None,
        rule: str | None = None,
        encoding: str | None = None,
        conflict_only: bool = False,
        batch_no: str | None = None,
        page: int = 1,
        size: int = 50,
    ) -> tuple[list[dict[str, Any]], int, dict[str, Any] | None]:
        batch = self._resolve_batch(batch_no)
        if batch is None:
            return [], 0, None
        rows = [row for row in store.rows(TABLE_ENTRY) if row.get("批次号") == batch["批次号"]]
        if host:
            rows = [row for row in rows if host.casefold() in str(row.get("主机", "")).casefold()]
        if rule:
            rows = [
                row for row in rows
                if any(rule.casefold() in str(code).casefold() for code in row.get("规则编号", []))
            ]
        if encoding:
            keyword = encoding.casefold()
            rows = [
                row for row in rows
                if any(keyword in str(enc).casefold() for enc in row.get("编码列表", []))
            ]
        if conflict_only:
            rows = [row for row in rows if row.get("是否冲突")]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total, batch

    def get_host_detail(
        self, host: str, batch_no: str | None = None
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        batch = self._resolve_batch(batch_no)
        if batch is None:
            return None, None
        for row in store.rows(TABLE_ENTRY):
            if row.get("批次号") == batch["批次号"] and str(row.get("主机", "")).casefold() == host.casefold():
                return row, batch
        return None, batch

    def list_conflicts(
        self, *, batch_no: str | None = None, host: str | None = None
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        batch = self._resolve_batch(batch_no)
        if batch is None:
            return [], None
        rows = [row for row in store.rows(TABLE_CONFLICT) if row.get("批次号") == batch["批次号"]]
        if host:
            rows = [row for row in rows if host.casefold() in str(row.get("主机", "")).casefold()]
        return rows, batch

    def list_trends(
        self, *, batch_no: str | None = None, host: str | None = None
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        batch = self._resolve_batch(batch_no)
        if batch is None:
            return [], None
        rows = [row for row in store.rows(TABLE_TREND) if row.get("批次号") == batch["批次号"]]
        if host:
            rows = [row for row in rows if host.casefold() in str(row.get("主机", "")).casefold()]
        rows.sort(key=lambda row: (-int(row.get("失败数", 0)) - int(row.get("乱码数", 0)), str(row.get("主机", ""))))
        return rows, batch

    def list_ledger(self, *, status: str | None = None, batch_no: str | None = None) -> list[dict[str, Any]]:
        self.ensure_current()
        rows = list(store.rows(TABLE_LEDGER))
        if batch_no:
            rows = [row for row in rows if row.get("批次号") == batch_no]
        if status:
            rows = [row for row in rows if row.get("状态") == status]
        rows.sort(key=lambda row: (str(row.get("批次号", "")), str(row.get("主机", ""))), reverse=True)
        return rows

    def review_ledger(
        self, ledger_id: int, action: str, operator: str = "监控值班"
    ) -> tuple[dict[str, Any] | None, str]:
        """台账复核：状态只在服务层流转，并同步冲突清单，保证两边读同一份数据。"""
        target = LEDGER_ACTIONS.get(action)
        if target is None:
            return None, f"动作「{action}」不属于待复核台账可执行范围"
        entry = store.find(TABLE_LEDGER, ledger_id)
        if entry is None:
            return None, f"台账记录 {ledger_id} 不存在或已归档"
        entry["状态"] = target
        if target == "已复核":
            entry["复核人"] = operator
            entry["复核时间"] = _now()
        else:
            entry["复核人"] = ""
            entry["复核时间"] = ""
        for conflict in store.rows(TABLE_CONFLICT):
            if conflict.get("批次号") == entry.get("批次号") and conflict.get("主机") == entry.get("主机"):
                conflict["状态"] = target
        return entry, f"台账记录已{action}"


host_index_service = HostIndexService()
