<template>
  <div class="app-shell">
    <aside class="app-side">
      <h1 class="app-title">特种设备点检运维平台</h1>
      <nav class="nav-list">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="app-main">
      <header class="app-head">
        <span class="head-desc">面向锅炉、压力容器、起重机械、电梯等特种设备的台账建档、日常点检、润滑保养、定期检验与隐患整改的一体化运维后台。</span>
        <span class="head-user">当前值班：{{ store.operator }} · {{ store.shiftLabel }}</span>
      </header>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
import { useSessionStore } from '@/stores/session'

const store = useSessionStore()

const navItems = [{ label: "运营概览", path: "/" }, { label: "锅炉设备", path: "/boiler" }, { label: "压力容器", path: "/vessel" }, { label: "压力管道", path: "/pressurepipe" }, { label: "起重机械", path: "/crane" }, { label: "电梯设备", path: "/elevator" }, { label: "场内机动车辆", path: "/forklift" }, { label: "点检计划", path: "/plan" }, { label: "点检记录", path: "/spotcheck" }, { label: "润滑保养", path: "/lubricate" }, { label: "定期检验", path: "/inspect" }, { label: "检验报告", path: "/report" }, { label: "隐患登记", path: "/hazard" }, { label: "整改闭环", path: "/rectify" }, { label: "使用登记", path: "/register" }, { label: "作业人员", path: "/operator" }, { label: "备件器材", path: "/spare" }, { label: "维保合同", path: "/contract" }, { label: "费用结算", path: "/settle" }, { label: "调度台账", path: "/dispatch" }]
</script>
