<template>
  <section class="page" data-module="monitor">
    <header class="page-head">
      <div><h2>采集监控</h2><p class="page-desc">维护监控面板，围绕面板编号、采集源总数、今日采集量、成功率做登记、筛选与状态流转。</p></div>
    </header>
    <div class="analysis-summary">
      <article v-for="m in summaryMetrics" :key="m.label" class="analysis-card" data-testid="kpi-card">
        <span style="font-size:12px;color:var(--muted)">{{ m.label }}</span>
        <strong style="font-size:22px;display:block">{{ m.value }}</strong>
        <span :class="m.trend > 0 ? 'trend-up' : 'trend-down'" style="font-size:12px">{{ m.trend > 0 ? '↑' : '↓' }}{{ Math.abs(m.trend) }}%</span>
      </article>
    </div>
    <form class="analysis-form" @submit.prevent="runAnalysis">
      <label v-for="field in paramFields" :key="field"><span>{{ field }}</span>
        <select v-if="field.includes('方法')||field.includes('策略')||field.includes('粒度')" v-model="params[field]"><option v-for="o in options[field]" :key="o" :value="o">{{ o }}</option></select>
        <input v-else v-model="params[field]" :placeholder="`请输入${field}`" />
      </label>
      <button class="btn primary" type="submit" data-testid="run-analysis">运行分析</button>
    </form>
    <div v-if="chartData.length" class="analysis-chart">
      <div v-for="(bar, i) in chartData" :key="i" class="analysis-bar" :style="{ height: barHeight(bar.value) + 'px' }"><span>{{ bar.label }}</span></div>
    </div>
    <table class="data-table" v-if="results.length">
      <thead><tr><th v-for="c in resultColumns" :key="c">{{ c }}</th></tr></thead>
      <tbody><tr v-for="row in results" :key="row.id"><td v-for="c in resultColumns" :key="c">{{ row[c] ?? '—' }}</td></tr></tbody>
    </table>
    <p v-if="!results.length && !loading" style="text-align:center;color:var(--muted)">请配置参数后运行分析</p>

    <section class="host-index" data-testid="monitor-host-index">
      <header class="page-head">
        <div>
          <h3>主机规则索引及冲突清单</h3>
          <p class="page-desc">
            监控面板通过自己的链路读取与采集规则服务同一份持久化快照；
            <span v-if="hostBatch">当前批次 {{ hostBatch.批次号 }} · 版本 {{ hostBatch.版本 }} · 生成于 {{ hostBatch.生成时间 }}。</span>
          </p>
        </div>
        <div class="page-actions">
          <label class="filter-item">
            <span>目标主机</span>
            <input v-model="hostKeyword" data-testid="monitor-filter-host" placeholder="按主机检索" @input="loadHostSnapshot" />
          </label>
        </div>
      </header>
      <table class="data-table">
        <thead>
          <tr><th>目标主机</th><th>规则数</th><th>当前编码</th><th>编码冲突</th><th>失败数</th><th>乱码数</th><th>最近抓取时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in hostIndex" :key="String(row.主机)" :data-conflict="row.是否冲突 ? '1' : '0'">
            <td>{{ row.主机 }}</td>
            <td>{{ row.规则数 }}</td>
            <td>{{ row.当前编码 }}</td>
            <td>{{ row.是否冲突 ? '是' : '否' }}</td>
            <td>{{ row.失败数 }}</td>
            <td>{{ row.乱码数 }}</td>
            <td>{{ row.最近抓取时间 || '—' }}</td>
          </tr>
          <tr v-if="!hostIndex.length"><td colspan="7" class="empty-state">暂无主机规则索引快照</td></tr>
        </tbody>
      </table>

      <h4 class="conflict-title">失败抓取趋势清单（按主机 + 编码归并）</h4>
      <table class="data-table" data-testid="trend-table">
        <thead>
          <tr><th>目标主机</th><th>字符编码</th><th>成功数</th><th>失败数</th><th>乱码数</th><th>趋势</th></tr>
        </thead>
        <tbody>
          <tr v-for="trend in trends" :key="`${trend.主机}-${trend.字符编码}`">
            <td>{{ trend.主机 }}</td>
            <td>{{ trend.字符编码 }}</td>
            <td>{{ trend.成功数 }}</td>
            <td>{{ trend.失败数 }}</td>
            <td>{{ trend.乱码数 }}</td>
            <td>
              <span :class="trend.趋势 === '上升' ? 'trend-down' : 'trend-up'">{{ trend.趋势 }}</span>
            </td>
          </tr>
          <tr v-if="!trends.length"><td colspan="6" class="empty-state">暂无失败抓取趋势数据</td></tr>
        </tbody>
      </table>

      <h4 class="conflict-title">待复核台账（编码冲突随批次落账）</h4>
      <table class="data-table" data-testid="ledger-table">
        <thead>
          <tr><th>批次号</th><th>目标主机</th><th>冲突编码</th><th>涉及规则数</th><th>状态</th><th>登记时间</th><th>复核人</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in ledger" :key="String(row.id)">
            <td>{{ row.批次号 }}</td>
            <td>{{ row.主机 }}</td>
            <td>{{ row.冲突编码 }}</td>
            <td>{{ row.涉及规则数 }}</td>
            <td>{{ row.状态 }}</td>
            <td>{{ row.登记时间 }}</td>
            <td>{{ row.复核人 || '—' }}</td>
            <td class="row-actions">
              <button
                v-if="row.状态 === '待复核'"
                class="link"
                type="button"
                :data-testid="`review-${row.id}`"
                @click="reviewLedger(row, '标记已复核')"
              >标记已复核</button>
              <button
                v-else
                class="link"
                type="button"
                :data-testid="`reopen-${row.id}`"
                @click="reviewLedger(row, '重新打开')"
              >重新打开</button>
            </td>
          </tr>
          <tr v-if="!ledger.length"><td colspan="8" class="empty-state">暂无待复核台账记录</td></tr>
        </tbody>
      </table>
    </section>
  </section>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { request } from '@/api/client'
const ENDPOINT = '/api/monitor'
const summaryMetrics = ref<{label:string;value:number;trend:number}[]>([])
const results = ref<any[]>([]); const chartData = ref<{label:string;value:number}[]>([])
const loading = ref(false)
const params = ref<Record<string,string>>({})
const paramFields = ["面板编号", "采集源总数", "今日采集量", "成功率", "平均延迟", "失败重试", "异常告警", "更新时间"].filter((f: string) => !['编号','名称','版本'].includes(f)).slice(0, 4)
const options: Record<string,string[]> = { '统计粒度': ['按日','按周','按月'], '分组字段': ['全量','按类型','按区域'], '比较方法': ['环比','同比','绝对值'], '时间范围': ['最近7天','最近30天','最近90天'] }
const resultColumns = computed(() => ["面板编号", "采集源总数", "今日采集量", "成功率", "平均延迟", "失败重试", "异常告警", "更新时间"].slice(0, 5))
function barHeight(v: number) { const max = Math.max(...chartData.value.map(d => d.value), 1); return Math.max(10, (v / max) * 140) }
async function fetchSummary() { try { const res = await request(`${ENDPOINT}/summary`); summaryMetrics.value = (await res.json()).metrics || [] } catch(e) {} }
async function runAnalysis() {
  loading.value = true
  try { const res = await request(`${ENDPOINT}/run`, { method: 'POST', body: JSON.stringify({ values: params.value }) }); const data = await res.json(); results.value = data.items || []; chartData.value = (data.items || []).map((r: any) => ({ label: Object.values(r)[0] as string, value: Object.values(r).filter(v => typeof v === 'number')[0] as number || 0 })).slice(0, 6) } catch(e) { results.value = [] }
  loading.value = false
}

// ---- 主机规则索引及冲突清单（与采集规则服务同一份快照） ----
type HostRow = Record<string, any>
const hostIndex = ref<HostRow[]>([])
const hostBatch = ref<HostRow | null>(null)
const trends = ref<HostRow[]>([])
const ledger = ref<HostRow[]>([])
const hostKeyword = ref('')

async function loadHostSnapshot() {
  try {
    const query = hostKeyword.value ? `?host=${encodeURIComponent(hostKeyword.value)}` : ''
    const res = await request(`${ENDPOINT}/host-index${query}`)
    const data = await res.json()
    hostIndex.value = data.items || []
    hostBatch.value = data.批次 || null
  } catch(e) { hostIndex.value = [] }
  try {
    const res = await request(`${ENDPOINT}/host-trends`)
    trends.value = (await res.json()).items || []
  } catch(e) { trends.value = [] }
  try {
    const res = await request(`${ENDPOINT}/review-ledger`)
    ledger.value = (await res.json()).items || []
  } catch(e) { ledger.value = [] }
}

async function reviewLedger(row: HostRow, action: string) {
  try {
    await request(`${ENDPOINT}/review-ledger/${row.id}/actions`, {
      method: 'POST', body: JSON.stringify({ action }),
    })
  } finally {
    await loadHostSnapshot()
  }
}

onMounted(() => { void fetchSummary(); void loadHostSnapshot() })
</script>
