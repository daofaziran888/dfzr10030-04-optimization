<template>
  <section class="page" data-module="crawler">
    <header class="page-head">
      <div>
        <h2>网页采集规则管理</h2>
        <p class="page-desc">维护采集规则，围绕规则编号、目标网址、页面选择器、正文选择器做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">登记采集规则</button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">导出网页采集规则清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button
              class="link"
              type="button"
              :data-testid="`locate-${row.id}`"
              @click="locateRuleHost(row)"
            >
              索引定位
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无网页采集规则数据，可先登记采集规则</td>
        </tr>
      </tbody>
    </table>

    <section class="host-index" data-testid="host-index">
      <header class="page-head">
        <div>
          <h3>主机规则索引及冲突清单</h3>
          <p class="page-desc">
            按目标主机归并采集规则，同一主机只占一个索引项；同一主机出现多个编码时进入冲突清单并保留全部编码，
            乱码排查可回溯到具体规则与最近抓取样本。
          </p>
        </div>
        <div class="page-actions">
          <button class="btn" data-testid="rebuild-index" type="button" :disabled="rebuilding" @click="rebuildIndex">
            {{ rebuilding ? '重算中…' : '重算索引' }}
          </button>
        </div>
      </header>

      <form class="filter-bar" @submit.prevent="loadHostIndex">
        <label class="filter-item">
          <span>目标主机</span>
          <input v-model="hostFilters.host" data-testid="filter-host" placeholder="按主机检索，如 news.example.com" />
        </label>
        <label class="filter-item">
          <span>规则编号</span>
          <input v-model="hostFilters.rule" data-testid="filter-rule" placeholder="按采集规则检索" />
        </label>
        <label class="filter-item">
          <span>字符编码</span>
          <input v-model="hostFilters.encoding" data-testid="filter-encoding" placeholder="如 utf-8 / gbk" />
        </label>
        <label class="filter-item">
          <span>批次版本</span>
          <select v-model="hostFilters.batch" data-testid="filter-batch">
            <option value="">当前批次</option>
            <option v-for="b in batches" :key="String(b.批次号)" :value="String(b.批次号)">
              {{ b.批次号 }}（{{ b.状态 }}）
            </option>
          </select>
        </label>
        <label class="filter-item">
          <span>只看冲突</span>
          <input v-model="hostFilters.conflictOnly" data-testid="filter-conflict-only" type="checkbox" />
        </label>
        <button class="btn" data-testid="query-host-index" type="submit">查询</button>
      </form>

      <p v-if="hostBatch" class="batch-line" data-testid="batch-line">
        展示批次 {{ hostBatch.批次号 }} · 版本 {{ hostBatch.版本 }} · {{ hostBatch.状态 }} · 生成于 {{ hostBatch.生成时间 }}
        · 主机 {{ hostBatch.主机数 }} 个 · 冲突 {{ hostBatch.冲突数 }} 条 · 命中 {{ hostTotal }} 个索引项
        <span v-if="indexMessage">· {{ indexMessage }}</span>
      </p>

      <table class="data-table">
        <thead>
          <tr>
            <th>目标主机</th>
            <th>规则数</th>
            <th>当前编码</th>
            <th>编码列表</th>
            <th>编码冲突</th>
            <th>成功/失败/乱码</th>
            <th>最近抓取时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="row in hostRows" :key="String(row.主机)">
            <tr :data-testid="`host-${row.主机}`" :data-conflict="row.是否冲突 ? '1' : '0'">
              <td>{{ row.主机 }}</td>
              <td>{{ row.规则数 }}</td>
              <td>{{ row.当前编码 }}</td>
              <td>{{ (row.编码列表 || []).join('、') }}</td>
              <td>{{ row.是否冲突 ? '是' : '否' }}</td>
              <td>{{ row.成功数 }}/{{ row.失败数 }}/{{ row.乱码数 }}</td>
              <td>{{ row.最近抓取时间 || '—' }}</td>
              <td>
                <button class="link" type="button" :data-testid="`expand-${row.主机}`" @click="toggleHost(String(row.主机))">
                  {{ expandedHost === row.主机 ? '收起' : '展开' }}
                </button>
              </td>
            </tr>
            <tr v-if="expandedHost === row.主机" class="nested-row">
              <td colspan="8">
                <div v-if="hostDetail" class="nested-block" :data-testid="`detail-${row.主机}`">
                  <h4>规则明细</h4>
                  <table class="data-table">
                    <thead>
                      <tr><th>规则编号</th><th>字符编码</th><th>状态</th><th>目标网址</th></tr>
                    </thead>
                    <tbody>
                      <tr v-for="item in hostDetail.规则明细" :key="String(item.规则编号)">
                        <td>{{ item.规则编号 }}</td>
                        <td>{{ item.字符编码 }}</td>
                        <td>{{ item.状态 }}</td>
                        <td>{{ item.目标网址 }}</td>
                      </tr>
                    </tbody>
                  </table>
                  <h4>最近抓取样本</h4>
                  <table class="data-table">
                    <thead>
                      <tr><th>样本编号</th><th>规则编号</th><th>抓取时间</th><th>抓取结果</th><th>检测编码</th><th>乱码标记</th><th>内容摘要</th></tr>
                    </thead>
                    <tbody>
                      <tr v-for="sample in hostDetail.样本快照" :key="String(sample.样本编号)">
                        <td>{{ sample.样本编号 }}</td>
                        <td>{{ sample.规则编号 }}</td>
                        <td>{{ sample.抓取时间 }}</td>
                        <td>{{ sample.抓取结果 }}</td>
                        <td>{{ sample.检测编码 || '—' }}</td>
                        <td>{{ sample.乱码标记 }}</td>
                        <td>{{ sample.内容摘要 }}</td>
                      </tr>
                      <tr v-if="!hostDetail.样本快照?.length">
                        <td colspan="7" class="empty-state">该主机暂无抓取样本</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <p v-else class="empty-state">明细加载中…</p>
              </td>
            </tr>
          </template>
          <tr v-if="!hostRows.length">
            <td colspan="8" class="empty-state">暂无主机规则索引，可点击重算索引生成</td>
          </tr>
        </tbody>
      </table>

      <h4 class="conflict-title">编码冲突清单</h4>
      <table class="data-table" data-testid="conflict-table">
        <thead>
          <tr>
            <th>目标主机</th>
            <th>冲突编码</th>
            <th>涉及规则</th>
            <th>样本证据</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="conflict in conflicts" :key="`${conflict.批次号}-${conflict.主机}`">
            <td>{{ conflict.主机 }}</td>
            <td>{{ (conflict.冲突编码 || []).join('、') }}</td>
            <td>
              {{ (conflict.涉及规则 || []).map((item: HostRuleItem) => `${item.规则编号}(${item.字符编码})`).join('；') }}
            </td>
            <td>{{ (conflict.样本证据 || []).map((item: HostSampleItem) => item.样本编号).join('、') || '—' }}</td>
            <td>{{ conflict.状态 }}</td>
          </tr>
          <tr v-if="!conflicts.length">
            <td colspan="5" class="empty-state">当前批次无编码冲突</td>
          </tr>
        </tbody>
      </table>
    </section>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记采集规则</h3>
        <label v-for="field in columns" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条网页采集规则记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type HostRuleItem = { 规则编号: string; 字符编码: string; 状态: string; 目标网址: string }
type HostSampleItem = {
  样本编号: string; 规则编号: string; 抓取时间: string; 抓取结果: string
  检测编码: string; 乱码标记: string; 内容摘要: string
}
type HostEntry = {
  批次号: string; 主机: string; 规则数: number; 规则编号: string[]
  当前编码: string; 编码列表: string[]; 是否冲突: boolean
  成功数: number; 失败数: number; 乱码数: number; 最近抓取时间: string
  规则明细: HostRuleItem[]; 样本快照: HostSampleItem[]
}
type BatchInfo = {
  批次号: string; 版本: number; 状态: string; 规则数: number; 主机数: number
  冲突数: number; 样本数: number; 触发来源: string; 生成时间: string
}
type ConflictItem = {
  批次号: string; 主机: string; 冲突编码: string[]
  涉及规则: HostRuleItem[]; 样本证据: HostSampleItem[]; 状态: string
}

const ENDPOINT = '/api/crawler'
const columns = ["规则编号", "目标网址", "页面选择器", "正文选择器", "翻页参数", "抓取频率", "字符编码", "去重策略"]
const actions = ["提交测试", "发布规则", "停用规则"]
const statuses = ["草稿", "测试中", "已发布", "已停用"]
const metricNames = ["规则总数", "已发布规则", "测试中规则"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const stats = computed(() => [
  { label: metricNames[0], value: total.value },
  { label: metricNames[1], value: rows.value.filter((row) => row.status === statuses[1]).length },
  { label: metricNames[2], value: rows.value.filter((row) => row.status === statuses[statuses.length - 1]).length },
])

// ---- 主机规则索引及冲突清单 ----
const hostRows = ref<HostEntry[]>([])
const hostTotal = ref(0)
const hostBatch = ref<BatchInfo | null>(null)
const batches = ref<BatchInfo[]>([])
const conflicts = ref<ConflictItem[]>([])
const hostFilters = ref({ host: '', rule: '', encoding: '', batch: '', conflictOnly: false })
const expandedHost = ref('')
const hostDetail = ref<HostEntry | null>(null)
const rebuilding = ref(false)
const indexMessage = ref('')

async function loadBatches() {
  try {
    const response = await request(`${ENDPOINT}/host-index/batches`)
    if (response.ok) batches.value = (await response.json()).items ?? []
  } catch {
    batches.value = []
  }
}

async function loadConflicts() {
  const query = new URLSearchParams()
  if (hostFilters.value.batch) query.set('batch', hostFilters.value.batch)
  if (hostFilters.value.host) query.set('host', hostFilters.value.host)
  try {
    const response = await request(`${ENDPOINT}/host-index/conflicts?${query}`)
    if (response.ok) conflicts.value = (await response.json()).items ?? []
  } catch {
    conflicts.value = []
  }
}

async function loadHostIndex() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (hostFilters.value.host) query.set('host', hostFilters.value.host)
  if (hostFilters.value.rule) query.set('rule', hostFilters.value.rule)
  if (hostFilters.value.encoding) query.set('encoding', hostFilters.value.encoding)
  if (hostFilters.value.batch) query.set('batch', hostFilters.value.batch)
  if (hostFilters.value.conflictOnly) query.set('conflict_only', 'true')
  try {
    const response = await request(`${ENDPOINT}/host-index?${query}`)
    if (!response.ok) throw new Error('主机规则索引读取失败')
    const payload = await response.json()
    hostRows.value = payload.items ?? []
    hostTotal.value = payload.total ?? 0
    hostBatch.value = payload.批次 ?? null
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '主机规则索引读取失败'
  }
  expandedHost.value = ''
  hostDetail.value = null
  await loadConflicts()
}

async function toggleHost(host: string) {
  if (expandedHost.value === host) {
    expandedHost.value = ''
    hostDetail.value = null
    return
  }
  errorMessage.value = ''
  const query = new URLSearchParams({ host })
  if (hostFilters.value.batch) query.set('batch', hostFilters.value.batch)
  try {
    const response = await request(`${ENDPOINT}/host-index/detail?${query}`)
    if (!response.ok) throw new Error('主机索引明细读取失败')
    const payload = await response.json()
    hostDetail.value = payload.item ?? null
    expandedHost.value = host
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '主机索引明细读取失败'
  }
}

async function rebuildIndex() {
  rebuilding.value = true
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/host-index/rebuild`, {
      method: 'POST', body: JSON.stringify({}),
    })
    const payload = await response.json()
    indexMessage.value = payload.message || ''
    hostFilters.value.batch = ''
    await loadBatches()
    await loadHostIndex()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '索引重算失败'
  } finally {
    rebuilding.value = false
  }
}

function locateRuleHost(row: Row) {
  hostFilters.value = { host: '', rule: String(row['规则编号'] ?? ''), encoding: '', batch: '', conflictOnly: false }
  void loadHostIndex()
}

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value).toString()
  try {
    const response = await request(`${ENDPOINT}/export?${query}`)
    if (!response.ok) throw new Error('导出失败，请稍后重试')
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = 'crawler.csv'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(columns.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST', body: JSON.stringify(createValues.value),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '登记失败')
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('网页采集规则动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '网页采集规则操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('采集规则列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '网页采集规则列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadBatches()
  void loadHostIndex()
})
</script>
