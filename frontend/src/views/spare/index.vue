<template>
  <section class="page" data-module="spare">
    <header class="page-head">
      <div>
        <h2>备件器材管理</h2>
        <p class="page-desc">维护备件器材，围绕备件编号、备件名称、适用设备、结存数量做登记、筛选与状态流转；入库、出库、盘点均落库并保留台账。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记备件器材</button>
        <button class="btn" type="button" @click="openStocktake">盘点</button>
        <button class="btn" type="button" @click="exportRows">导出备件器材清单</button>
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
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button class="link" type="button" @click="openStockIn(row)">入库</button>
            <button class="link" type="button" @click="openStockOut(row)">出库</button>
            <button class="link" type="button" @click="openRectify(row)">整改</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无备件器材数据，可先登记备件器材</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条备件器材记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-if="successMessage" class="success-text">{{ successMessage }}</span>
    </footer>

    <!-- 出入库台账 -->
    <section class="ledger-section">
      <header class="ledger-head">
        <h3>出入库台账</h3>
        <form class="filter-bar" @submit.prevent="reloadLedger">
          <label class="filter-item">
            <span>业务类型</span>
            <select v-model="ledgerFilters.biz_type">
              <option value="">全部</option>
              <option v-for="t in ledgerTypes" :key="t" :value="t">{{ t }}</option>
            </select>
          </label>
          <label class="filter-item">
            <span>备件编号</span>
            <input v-model="ledgerFilters.keyword" placeholder="按备件编号检索" />
          </label>
          <button class="btn" type="submit">查询</button>
          <button class="btn ghost" type="button" @click="resetLedgerFilters">重置</button>
        </form>
      </header>
      <table class="data-table">
        <thead>
          <tr>
            <th>发生时间</th>
            <th>备件编号</th>
            <th>业务类型</th>
            <th>批次号</th>
            <th>数量</th>
            <th>结存后数量</th>
            <th>库位</th>
            <th>备注</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in ledgerRows" :key="String(item.id)">
            <td>{{ item['发生时间'] ?? '—' }}</td>
            <td>{{ item['备件编号'] ?? '—' }}</td>
            <td>{{ item['业务类型'] ?? '—' }}</td>
            <td>{{ item['批次号'] ?? '—' }}</td>
            <td>{{ item['数量'] ?? '—' }}</td>
            <td>{{ item['结存后数量'] ?? '—' }}</td>
            <td>{{ item['库位'] ?? '—' }}</td>
            <td>{{ item['备注'] ?? '—' }}</td>
          </tr>
          <tr v-if="!ledgerRows.length">
            <td colspan="8" class="empty-state">暂无出入库台账</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>共 {{ ledgerTotal }} 条台账记录（历史台账只增不改，始终保留）</span>
      </footer>
    </section>

    <!-- 操作弹窗 -->
    <div v-if="modal.open" class="modal-mask" @click.self="closeModal">
      <div class="modal">
        <h3>{{ modal.title }}</h3>
        <div class="modal-body">
          <template v-if="modal.mode === 'stocktake'">
            <p class="modal-tip">盘点结果将直接回写结存数量，与存放库位明细同步；差异计入台账。</p>
            <label class="form-item">
              <span>盘点单号</span>
              <input v-model="modal.form['盘点单号']" placeholder="留空自动生成" />
            </label>
            <label class="form-item">
              <span>盘点日期</span>
              <input v-model="modal.form['盘点日期']" type="date" />
            </label>
            <label class="form-item">
              <span>盘点人</span>
              <input v-model="modal.form['盘点人']" placeholder="盘点人员" />
            </label>
            <table class="data-table">
              <thead>
                <tr><th>备件编号</th><th>备件名称</th><th>账面数量</th><th>实盘数量</th></tr>
              </thead>
              <tbody>
                <tr v-for="(item, idx) in modal.form['明细']" :key="item['备件编号']">
                  <td>{{ item['备件编号'] }}</td>
                  <td>{{ item['备件名称'] }}</td>
                  <td>{{ item['账面数量'] }}</td>
                  <td>
                    <input v-model.number="modal.form['明细'][idx]['实盘数量']" type="number" min="0" step="any" />
                  </td>
                </tr>
              </tbody>
            </table>
          </template>
          <template v-else>
            <p class="modal-tip" v-if="modal.row">
              备件：{{ modal.row['备件编号'] }} · {{ modal.row['备件名称'] }} · 当前结存 {{ modal.row['结存数量'] }} {{ modal.row['计量单位'] }}
            </p>
            <label class="form-item" v-if="modal.mode === 'rectify'">
              <span>整改结论</span>
              <textarea v-model="modal.form['整改结论']" rows="3" placeholder="整改完成情况与结论，将落到调度台账" />
            </label>
            <label class="form-item" v-if="modal.mode === 'rectify'">
              <span>调度内容</span>
              <input v-model="modal.form['调度内容']" placeholder="需要调度跟踪的内容" />
            </label>
            <label class="form-item" v-if="modal.mode !== 'rectify'">
              <span>数量</span>
              <input v-model.number="modal.form['数量']" type="number" min="0" step="any" placeholder="本次入库/出库数量" />
            </label>
            <label class="form-item" v-if="modal.mode !== 'rectify'">
              <span>批次号</span>
              <input v-model="modal.form['批次号']" placeholder="批次号，用于幂等去重" />
            </label>
            <label class="form-item">
              <span>备注</span>
              <input v-model="modal.form['备注']" placeholder="备注（选填）" />
            </label>
          </template>
        </div>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="submitModal">确认</button>
          <button class="btn ghost" type="button" @click="closeModal">取消</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

const ENDPOINT = '/api/spare'
const columns = ["备件编号", "备件名称", "适用设备", "结存数量", "计量单位", "存放库位", "保管人员", "备件状态"]
const actions = ["冻结备件", "解冻备件", "登记耗尽"]
const statuses = ["正常可用", "储备不足", "已冻结", "已耗尽"]
const stats = [{ label: "可用备件", value: 0 }, { label: "储备不足备件", value: 0 }, { label: "已冻结备件", value: 0 }]
const ledgerTypes = ["入库", "出库", "盘盈", "盘亏"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const successMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const ledgerRows = ref<Row[]>([])
const ledgerTotal = ref(0)
const ledgerFilters = ref<Record<string, string>>({})

const modal = reactive<{
  open: boolean
  mode: 'in' | 'out' | 'rectify' | 'stocktake'
  title: string
  row: Row | null
  form: Record<string, any>
}>({
  open: false,
  mode: 'in',
  title: '',
  row: null,
  form: {},
})

function resetFilters() {
  filters.value = {}
  void reload()
}

function resetLedgerFilters() {
  ledgerFilters.value = {}
  void reloadLedger()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '备件器材登记入口尚未接入审批流'
}

function openStockIn(row: Row) {
  modal.open = true
  modal.mode = 'in'
  modal.title = '备件入库'
  modal.row = row
  modal.form = { 数量: 1, 批次号: '', 备注: '' }
}

function openStockOut(row: Row) {
  modal.open = true
  modal.mode = 'out'
  modal.title = '备件出库'
  modal.row = row
  modal.form = { 数量: 1, 批次号: '', 备注: '' }
}

function openRectify(row: Row) {
  modal.open = true
  modal.mode = 'rectify'
  modal.title = '备件整改（结论落调度台账）'
  modal.row = row
  modal.form = { 整改结论: '', 调度内容: '', 备注: '' }
}

function openStocktake() {
  modal.open = true
  modal.mode = 'stocktake'
  modal.title = '备件盘点'
  modal.row = null
  modal.form = {
    盘点单号: '',
    盘点日期: new Date().toISOString().slice(0, 10),
    盘点人: '',
    明细: rows.value.map((r) => ({
      备件编号: r['备件编号'],
      备件名称: r['备件名称'],
      账面数量: r['结存数量'],
      实盘数量: r['结存数量'],
    })),
  }
}

function closeModal() {
  modal.open = false
}

async function submitModal() {
  errorMessage.value = ''
  successMessage.value = ''
  try {
    let url = ''
    let body: Record<string, any> = {}
    if (modal.mode === 'stocktake') {
      url = `${ENDPOINT}/stocktake`
      body = { values: { ...modal.form } }
    } else if (modal.mode === 'rectify') {
      url = `${ENDPOINT}/${modal.row!.id}/rectify`
      body = { values: { ...modal.form } }
    } else {
      const path = modal.mode === 'in' ? 'stock-in' : 'stock-out'
      url = `${ENDPOINT}/${modal.row!.id}/${path}`
      body = { values: { ...modal.form } }
    }
    const response = await request(url, { method: 'POST', body: JSON.stringify(body) })
    const payload = await response.json().catch(() => ({}))
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || '操作未生效，请稍后重试')
    }
    successMessage.value = payload.message || '操作成功'
    closeModal()
    await Promise.all([reload(), reloadLedger()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json().catch(() => ({}))
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || '备件器材动作未生效，请稍后重试')
    }
    successMessage.value = payload.message || '操作成功'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '备件器材操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) throw new Error('备件器材列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '备件器材列表读取失败'
  }
}

async function reloadLedger() {
  const params = new URLSearchParams()
  if (ledgerFilters.value.biz_type) params.set('biz_type', ledgerFilters.value.biz_type)
  if (ledgerFilters.value.keyword) params.set('keyword', ledgerFilters.value.keyword)
  params.set('size', '50')
  try {
    const response = await request(`${ENDPOINT}/ledger?${params.toString()}`)
    if (!response.ok) throw new Error('出入库台账读取失败')
    const payload = await response.json()
    ledgerRows.value = payload.items ?? []
    ledgerTotal.value = payload.total ?? ledgerRows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '出入库台账读取失败'
  }
}

onMounted(() => {
  void reload()
  void reloadLedger()
})
</script>

<style scoped>
.ledger-section {
  margin-top: 24px;
  border-top: 2px solid var(--border, #e5e7eb);
  padding-top: 16px;
}
.ledger-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 12px;
}
.ledger-head h3 {
  margin: 0;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.modal {
  background: #fff;
  border-radius: 8px;
  padding: 20px 24px;
  width: min(720px, 92vw);
  max-height: 86vh;
  overflow: auto;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}
.modal h3 {
  margin: 0 0 12px;
}
.modal-tip {
  color: #6b7280;
  font-size: 13px;
  margin: 0 0 12px;
}
.form-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 12px;
}
.form-item span {
  font-size: 13px;
  color: #374151;
}
.form-item input,
.form-item textarea,
.form-item select {
  padding: 6px 8px;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  font-size: 14px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
.success-text {
  color: #059669;
}
</style>
