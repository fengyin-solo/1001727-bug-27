<template>
  <section class="page" data-module="rectify">
    <header class="page-head">
      <div>
        <h2>整改闭环管理</h2>
        <p class="page-desc">维护整改单，围绕整改单号、关联隐患、整改措施、责任单位做登记、筛选与状态流转；备件类整改闭环时整改结论自动落入调度台账。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记整改单</button>
        <button class="btn" type="button" @click="exportRows">导出整改闭环清单</button>
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
              v-for="action in actionsFor(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无整改闭环数据，可先登记整改单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条整改闭环记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 确认闭环弹窗：填写整改结论；关联备件后结论落调度台账 -->
    <div v-if="closeForm" class="modal-mask" @click.self="closeForm = null">
      <div class="modal">
        <h3>确认闭环：{{ closeForm.整改单号 }}</h3>
        <p class="page-desc">整改结论为必填；填写关联备件编号后，结论将随闭环生成一条调度台账（重复提交闭环不会重复建账）。</p>
        <label class="form-line"><span>整改结论</span><textarea v-model="closeForm.整改结论" rows="3" placeholder="例如：密封垫圈老化，已更换并复查合格"></textarea></label>
        <label class="form-line"><span>关联备件编号</span><input v-model="closeForm.关联备件" placeholder="备件类整改必填，如 SPAR-0001" /></label>
        <label class="form-line"><span>调度数量</span><input v-model.number="closeForm.调度数量" type="number" min="0" placeholder="需要调度的备件数量，可为 0" /></label>
        <label class="form-line"><span>验收人员</span><input v-model="closeForm.验收人员" /></label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="closeForm = null">取消</button>
          <button class="btn primary" type="button" @click="submitClose">确认闭环并落台账</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/rectify'
const columns = ['整改单号', '关联隐患', '整改措施', '责任单位', '整改期限', '完成日期', '验收人员', '整改状态']
const stats = [{ label: '待下发整改', value: 0 }, { label: '整改中单据', value: 0 }, { label: '待验收闭环', value: 0 }]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = ['整改单号', '关联隐患', '整改措施']

type CloseForm = {
  id: number
  整改单号: string
  整改结论: string
  关联备件: string
  调度数量: number | null
  验收人员: string
}
const closeForm = ref<CloseForm | null>(null)

function actionsFor(row: Row): string[] {
  switch (row['status']) {
    case '待下发':
      return ['下发整改']
    case '整改中':
      return ['提交验收']
    case '待验收':
      return ['确认闭环']
    default:
      return []
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '整改单登记入口尚未接入审批流'
}

function runAction(action: string, row: Row) {
  errorMessage.value = ''
  if (action === '确认闭环') {
    closeForm.value = {
      id: row.id as number,
      整改单号: String(row.整改单号 ?? ''),
      整改结论: String(row.整改结论 ?? ''),
      关联备件: String(row.关联备件 ?? ''),
      调度数量: null,
      验收人员: String(row.验收人员 ?? ''),
    }
    return
  }
  void submitSimple(action, row)
}

async function submitSimple(action: string, row: Row) {
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      errorMessage.value = payload.message || '整改动作未生效'
      return
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '整改闭环操作失败'
  }
}

async function submitClose() {
  if (!closeForm.value) return
  const form = closeForm.value
  if (!form.整改结论.trim()) {
    errorMessage.value = '请填写整改结论'
    return
  }
  try {
    const response = await request(`${ENDPOINT}/${form.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({
        values: {
          action: '确认闭环',
          整改结论: form.整改结论,
          关联备件: form.关联备件,
          调度数量: form.调度数量 ?? 0,
          验收人员: form.验收人员,
        },
      }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      errorMessage.value = payload.message || '闭环未生效'
      return
    }
    errorMessage.value = payload.message
    closeForm.value = null
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '整改闭环操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('整改单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '整改闭环列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.modal-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); display: flex; align-items: center; justify-content: center; z-index: 20; }
.modal { background: #fff; border-radius: 8px; padding: 18px 20px; width: 520px; max-height: 85vh; overflow: auto; }
.modal h3 { margin: 0 0 6px; }
.form-line { display: flex; align-items: flex-start; gap: 10px; margin: 8px 0; font-size: 13px; }
.form-line > span { width: 96px; color: var(--muted); flex: none; padding-top: 5px; }
.form-line input, .form-line textarea { flex: 1; padding: 5px 8px; border: 1px solid var(--border); border-radius: 5px; font-family: inherit; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
</style>
