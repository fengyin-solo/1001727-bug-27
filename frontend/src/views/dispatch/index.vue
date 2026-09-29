<template>
  <section class="page" data-module="dispatch">
    <header class="page-head">
      <div>
        <h2>调度台账</h2>
        <p class="page-desc">备件器材整改结论等调度记录统一落在此处，供调度环节跟踪闭环。</p>
      </div>
    </header>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>调度单号 / 备件编号</span>
        <input v-model="filters.keyword" placeholder="按调度单号或备件编号检索" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="filters.status">
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
          <th>调度单号</th>
          <th>来源模块</th>
          <th>备件编号</th>
          <th>备件名称</th>
          <th>整改结论</th>
          <th>调度内容</th>
          <th>状态</th>
          <th>登记时间</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>{{ row['调度单号'] ?? '—' }}</td>
          <td>{{ row['来源模块'] ?? '—' }}</td>
          <td>{{ row['备件编号'] ?? '—' }}</td>
          <td>{{ row['备件名称'] ?? '—' }}</td>
          <td>{{ row['整改结论'] ?? '—' }}</td>
          <td>{{ row['调度内容'] ?? '—' }}</td>
          <td>{{ row['状态'] ?? '—' }}</td>
          <td>{{ row['登记时间'] ?? '—' }}</td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="8" class="empty-state">暂无调度台账记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条调度记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

const ENDPOINT = '/api/dispatch'
const statuses = ['待调度', '已调度', '已完成']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})

function resetFilters() {
  filters.value = {}
  void reload()
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (filters.value.keyword) params.set('keyword', filters.value.keyword)
  if (filters.value.status) params.set('status', filters.value.status)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) throw new Error('调度台账读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '调度台账读取失败'
  }
}

onMounted(reload)
</script>
