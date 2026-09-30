<template>
  <section class="page" data-module="spare">
    <header class="page-head">
      <div>
        <h2>备件器材管理</h2>
        <p class="page-desc">结存数量由存放库位明细实时汇总；冻结库位禁止出库；出入库与盘点全部落库并保留台账。</p>
      </div>
      <div class="page-actions">
        <button class="btn" :class="{ primary: tab === 'spares' }" type="button" @click="tab = 'spares'">备件与库位</button>
        <button class="btn" :class="{ primary: tab === 'ledger' }" type="button" @click="switchLedger">出入库台账</button>
        <button class="btn" type="button" @click="exportRows">导出备件清单</button>
      </div>
    </header>

    <div v-if="tab === 'spares'">
      <div class="stat-row">
        <article v-for="item in stats" :key="item.label" class="stat-card">
          <span class="stat-label">{{ item.label }}</span>
          <strong class="stat-value">{{ item.value }}</strong>
        </article>
      </div>

      <form class="filter-bar" @submit.prevent="reload">
        <label class="filter-item">
          <span>备件编号</span>
          <input v-model="keyword" placeholder="按备件编号检索" />
        </label>
        <label class="filter-item">
          <span>备件状态</span>
          <select v-model="statusFilter">
            <option value="">全部</option>
            <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
          </select>
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in columns" :key="column">{{ column }}</th>
            <th>库位/数量/状态</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="String(row.id)">
            <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
            <td>
              <div v-for="loc in row.库位明细" :key="loc.库位明细ID" class="loc-line">
                <span>{{ loc.存放库位 }}：{{ loc.库位数量 }}</span>
                <em :class="loc.库位冻结 ? 'tag frozen' : 'tag ok'">{{ loc.库位状态 }}</em>
                <button class="link" type="button" @click="toggleLocation(row, loc)">
                  {{ loc.库位冻结 ? '解冻库位' : '冻结库位' }}
                </button>
              </div>
            </td>
            <td class="row-actions">
              <button class="link" type="button" @click="openMove('出库', row)">出库</button>
              <button class="link" type="button" @click="openMove('入库', row)">入库</button>
              <button class="link" type="button" @click="openStocktake(row)">盘点</button>
              <button class="link" type="button" @click="runPartAction(row.备件状态 === '已冻结' ? '解冻备件' : '冻结备件', row)">
                {{ row.备件状态 === '已冻结' ? '解冻全部库位' : '冻结全部库位' }}
              </button>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td :colspan="columns.length + 2" class="empty-state">暂无备件器材数据</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span>共 {{ total }} 条备件器材记录，结存数量为各存放库位明细之和</span>
        <span v-if="message" class="error-text">{{ message }}</span>
      </footer>
    </div>

    <div v-else>
      <form class="filter-bar" @submit.prevent="reloadLedger">
        <label class="filter-item">
          <span>备件编号</span>
          <input v-model="ledgerFilter.备件编号" placeholder="按备件编号检索" />
        </label>
        <label class="filter-item">
          <span>台账类型</span>
          <select v-model="ledgerFilter.台账类型">
            <option value="">全部</option>
            <option>出库</option>
            <option>入库</option>
            <option>盘点调整</option>
          </select>
        </label>
        <label class="filter-item">
          <span>批次号</span>
          <input v-model="ledgerFilter.批次号" placeholder="按批次号追溯" />
        </label>
        <button class="btn" type="submit">查询</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in ledgerColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in ledgerRows" :key="String(row.id)">
            <td v-for="column in ledgerColumns" :key="column">{{ row[column] ?? '—' }}</td>
          </tr>
          <tr v-if="!ledgerRows.length">
            <td :colspan="ledgerColumns.length" class="empty-state">暂无出入库台账</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>共 {{ ledgerTotal }} 条台账记录，历史记录只追加、不修改</span>
        <span v-if="message" class="error-text">{{ message }}</span>
      </footer>
    </div>

    <!-- 出入库弹窗 -->
    <div v-if="moveForm" class="modal-mask" @click.self="moveForm = null">
      <div class="modal">
        <h3>{{ moveForm.type }}登记</h3>
        <p class="page-desc">同批次号重复提交只生效一次；{{ moveForm.type === '出库' ? '冻结库位会被服务端拒绝' : '入库可登记到新库位' }}。</p>
        <label class="form-line"><span>备件编号</span><input v-model="moveForm.备件编号" :disabled="true" /></label>
        <label class="form-line"><span>存放库位</span>
          <input v-if="moveForm.type === '入库' && !moveForm.allowExisting" v-model="moveForm.存放库位" list="loc-list" placeholder="选择已有库位或填写新库位" />
          <select v-else v-model="moveForm.存放库位">
            <option v-for="loc in moveForm.locations" :key="loc.存放库位" :value="loc.存放库位">
              {{ loc.存放库位 }}（{{ loc.库位状态 }}，现存 {{ loc.库位数量 }}）
            </option>
          </select>
          <datalist id="loc-list">
            <option v-for="loc in moveForm.locations" :key="loc.存放库位" :value="loc.存放库位" />
          </datalist>
        </label>
        <label class="form-line"><span>数量</span><input v-model.number="moveForm.数量" type="number" min="1" /></label>
        <label class="form-line"><span>批次号</span><input v-model="moveForm.批次号" placeholder="同一批次重复提交自动幂等" /></label>
        <label class="form-line"><span>经办人员</span><input v-model="moveForm.经办人员" /></label>
        <label class="form-line"><span>备注</span><input v-model="moveForm.备注" /></label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="moveForm = null">取消</button>
          <button class="btn primary" type="button" @click="submitMove">确认{{ moveForm.type }}</button>
        </div>
      </div>
    </div>

    <!-- 盘点弹窗 -->
    <div v-if="checkForm" class="modal-mask" @click.self="checkForm = null">
      <div class="modal">
        <h3>盘点调整：{{ checkForm.备件编号 }}</h3>
        <p class="page-desc">按实盘数量提交后，存放库位明细与结存总量在同一事务同步；同批次号重复提交只生效一次。</p>
        <div v-for="(item, idx) in checkForm.盘点明细" :key="idx" class="form-line">
          <span>{{ item.存放库位 }}</span>
          <span class="muted">账存 {{ item.账存 }}</span>
          <input v-model.number="item.库位数量" type="number" min="0" />
        </div>
        <button class="btn" type="button" @click="addCheckLine">+ 新增盘到库位</button>
        <label class="form-line"><span>新库位名称</span><input v-model="checkForm.新库位" placeholder="填写后点击新增" /></label>
        <label class="form-line"><span>盘点批次号</span><input v-model="checkForm.批次号" /></label>
        <label class="form-line"><span>盘点人员</span><input v-model="checkForm.经办人员" /></label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="checkForm = null">取消</button>
          <button class="btn primary" type="button" @click="submitStocktake">提交盘点</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Loc = { 库位明细ID: number; 存放库位: string; 库位数量: number; 库位冻结: boolean; 库位状态: string }
type Row = Record<string, string | number | null> & { 库位明细: Loc[]; 备件编号: string; 备件状态: string }

const ENDPOINT = '/api/spare'
const columns = ['备件编号', '备件名称', '适用设备', '结存数量', '计量单位', '存放库位', '保管人员', '备件状态']
const ledgerColumns = ['备件编号', '存放库位', '台账类型', '变动数量', '结存数量', '批次号', '经办人员', '备注', '发生时间']
const statuses = ['正常可用', '储备不足', '已冻结', '已耗尽']

const tab = ref<'spares' | 'ledger'>('spares')
const rows = ref<Row[]>([])
const total = ref(0)
const message = ref('')
const keyword = ref('')
const statusFilter = ref('')

const ledgerRows = ref<Record<string, string | number | null>[]>([])
const ledgerTotal = ref(0)
const ledgerFilter = reactive({ 备件编号: '', 台账类型: '', 批次号: '' })

const stats = computed(() => [
  { label: '备件种类', value: total.value },
  { label: '正常可用', value: rows.value.filter((r) => r.备件状态 === '正常可用').length },
  { label: '储备不足', value: rows.value.filter((r) => r.备件状态 === '储备不足').length },
  { label: '含冻结库位备件', value: rows.value.filter((r) => r.库位明细.some((l) => l.库位冻结)).length },
])

type MoveForm = {
  type: '出库' | '入库'
  备件编号: string
  存放库位: string
  locations: Loc[]
  allowExisting: boolean
  数量: number | null
  批次号: string
  经办人员: string
  备注: string
}
const moveForm = ref<MoveForm | null>(null)

type CheckLine = { 存放库位: string; 账存: number; 库位数量: number | null }
type CheckForm = {
  id: number
  备件编号: string
  盘点明细: CheckLine[]
  新库位: string
  批次号: string
  经办人员: string
}
const checkForm = ref<CheckForm | null>(null)

function batchPrefix() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function reload() {
  message.value = ''
  const params = new URLSearchParams()
  if (keyword.value) params.set('keyword', keyword.value)
  if (statusFilter.value) params.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    const payload = await response.json()
    rows.value = (payload.items ?? []) as Row[]
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    message.value = error instanceof Error ? error.message : '备件列表读取失败'
  }
}

async function postAction(path: string, body: Record<string, unknown>, okText: string) {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  const payload = await response.json()
  if (!payload.ok) {
    message.value = payload.message || '操作未生效'
    return false
  }
  message.value = okText || payload.message
  return true
}

async function runPartAction(action: string, row: Row) {
  message.value = ''
  const ok = await postAction(
    `${ENDPOINT}/${row.id}/actions`,
    { values: { action } },
    action === '冻结备件' ? '已冻结该备件的全部库位' : '已解冻该备件的全部库位',
  )
  if (ok) await reload()
}

async function toggleLocation(row: Row, loc: Loc) {
  message.value = ''
  const action = loc.库位冻结 ? '解冻库位' : '冻结库位'
  const ok = await postAction(
    `${ENDPOINT}/locations/${loc.库位明细ID}/actions`,
    { values: { action } },
    `${loc.存放库位}已${action.slice(2)}`,
  )
  if (ok) await reload()
}

function openMove(type: '出库' | '入库', row: Row) {
  const preferred = type === '出库'
    ? row.库位明细.find((l) => !l.库位冻结 && l.库位数量 > 0)
    : row.库位明细[0]
  moveForm.value = {
    type,
    备件编号: row.备件编号,
    存放库位: preferred?.存放库位 ?? '',
    locations: row.库位明细,
    // 出库只能选已有库位；入库默认选已有库位，可切换为手填新库位
    allowExisting: type === '出库' || !!preferred,
    数量: null,
    批次号: `${type === '出库' ? 'OUT' : 'IN'}-${batchPrefix()}`,
    经办人员: '',
    备注: '',
  }
}

async function submitMove() {
  if (!moveForm.value) return
  const form = moveForm.value
  if (!form.存放库位 || !form.数量) {
    message.value = '请选择库位并填写数量'
    return
  }
  const path = form.type === '出库' ? `${ENDPOINT}/outbound` : `${ENDPOINT}/inbound`
  const ok = await postAction(path, {
    values: {
      备件编号: form.备件编号,
      存放库位: form.存放库位,
      数量: form.数量,
      批次号: form.批次号,
      经办人员: form.经办人员,
      备注: form.备注,
      // 前端兜底幂等键：双击/网络重试时，服务端凭它只生效一次
      idem_key: form.批次号,
    },
  }, `${form.type}已登记并更新库存`)
  if (ok) {
    moveForm.value = null
    await reload()
  }
}

function openStocktake(row: Row) {
  checkForm.value = {
    id: row.id as number,
    备件编号: row.备件编号,
    盘点明细: row.库位明细.map((l) => ({ 存放库位: l.存放库位, 账存: l.库位数量, 库位数量: l.库位数量 })),
    新库位: '',
    批次号: `PD-${batchPrefix()}`,
    经办人员: '',
  }
}

function addCheckLine() {
  if (!checkForm.value) return
  const name = checkForm.value.新库位.trim()
  if (!name) {
    message.value = '请先填写新盘到的库位名称'
    return
  }
  if (checkForm.value.盘点明细.some((i) => i.存放库位 === name)) {
    message.value = '该库位已在盘点明细中'
    return
  }
  checkForm.value.盘点明细.push({ 存放库位: name, 账存: 0, 库位数量: 0 })
  checkForm.value.新库位 = ''
  message.value = ''
}

async function submitStocktake() {
  if (!checkForm.value) return
  const form = checkForm.value
  if (form.盘点明细.some((i) => i.库位数量 === null || i.库位数量 < 0)) {
    message.value = '请为每个库位填写不小于 0 的实盘数量'
    return
  }
  const ok = await postAction(`${ENDPOINT}/stocktake`, {
    values: {
      备件编号: form.备件编号,
      批次号: form.批次号,
      经办人员: form.经办人员,
      idem_key: form.批次号,
      盘点明细: form.盘点明细.map((i) => ({ 存放库位: i.存放库位, 库位数量: i.库位数量 })),
    },
  }, '盘点已落库，库位明细与结存总量已同步')
  if (ok) {
    checkForm.value = null
    await reload()
  }
}

async function reloadLedger() {
  message.value = ''
  const params = new URLSearchParams()
  if (ledgerFilter.备件编号) params.set('spare_code', ledgerFilter.备件编号)
  if (ledgerFilter.台账类型) params.set('change_type', ledgerFilter.台账类型)
  if (ledgerFilter.批次号) params.set('batch_no', ledgerFilter.批次号)
  try {
    const response = await request(`${ENDPOINT}/ledger?${params.toString()}`)
    const payload = await response.json()
    ledgerRows.value = payload.items ?? []
    ledgerTotal.value = payload.total ?? 0
  } catch (error) {
    message.value = error instanceof Error ? error.message : '台账读取失败'
  }
}

function switchLedger() {
  tab.value = 'ledger'
  void reloadLedger()
}

onMounted(reload)
</script>

<style scoped>
.loc-line { display: flex; gap: 8px; align-items: center; padding: 2px 0; white-space: nowrap; }
.tag { font-style: normal; font-size: 12px; padding: 0 6px; border-radius: 4px; }
.tag.frozen { background: #fef3c7; color: #b45309; }
.tag.ok { background: #dcfce7; color: #15803d; }
.muted { color: var(--muted); font-size: 12px; }
.modal-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); display: flex; align-items: center; justify-content: center; z-index: 20; }
.modal { background: #fff; border-radius: 8px; padding: 18px 20px; width: 480px; max-height: 85vh; overflow: auto; }
.modal h3 { margin: 0 0 6px; }
.form-line { display: flex; align-items: center; gap: 10px; margin: 8px 0; font-size: 13px; }
.form-line > span { width: 84px; color: var(--muted); flex: none; }
.form-line input, .form-line select { flex: 1; padding: 5px 8px; border: 1px solid var(--border); border-radius: 5px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
</style>
