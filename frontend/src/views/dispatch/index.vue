<template>
  <section class="page" data-module="dispatch">
    <header class="page-head">
      <div>
        <h2>调度台账</h2>
        <p class="page-desc">备件器材的整改结论在整改单确认闭环时自动落入本台账；台账只追加、不修改，一张整改单只生成一条调度记录。</p>
      </div>
    </header>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>调度单号/内容/结论</span>
        <input v-model="keyword" placeholder="按关键字检索" />
      </label>
      <label class="filter-item">
        <span>备件编号</span>
        <input v-model="spareCode" placeholder="按备件编号过滤" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length" class="empty-state">暂无调度台账，备件类整改单闭环后会自动登记</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条调度台账记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/dispatch'
const columns = ['调度单号', '来源', '关联整改单', '备件编号', '备件名称', '调度内容', '整改结论', '调度数量', '调度状态', '经办人员', '登记时间']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const spareCode = ref('')

function resetFilters() {
  keyword.value = ''
  spareCode.value = ''
  void reload()
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (keyword.value) params.set('keyword', keyword.value)
  if (spareCode.value) params.set('spare_code', spareCode.value)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) throw new Error('调度台账读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? 0
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '调度台账读取失败'
  }
}

onMounted(reload)
</script>
