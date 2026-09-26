<template>
  <section class="page" data-module="truck">
    <header class="page-head">
      <div>
        <h2>集卡调度管理</h2>
        <p class="page-desc">维护集卡，围绕调度单号、集卡牌号、司机姓名、作业任务做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记集卡</button>
        <button class="btn" type="button" @click="exportRows">导出集卡调度清单</button>
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
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] || '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              :class="['link', { disabled: !canRun(row, action) }]"
              type="button"
              @click="runAction(action, row, afterListAction)"
            >
              {{ action }}
            </button>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无集卡调度数据，可先登记集卡</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条集卡调度记录</span>
      <span v-if="errorMessage" :class="lastOk ? 'info-text' : 'error-text'">{{ errorMessage }}</span>
    </footer>

    <div v-if="detail" class="modal-mask" @click.self="closeDetail">
      <div class="modal-card">
        <header class="modal-head">
          <h3>调度单 {{ detail['调度单号'] }}</h3>
          <button class="btn ghost" type="button" @click="closeDetail">关闭</button>
        </header>
        <dl class="detail-grid">
          <template v-for="column in columns" :key="column">
            <dt>{{ column }}</dt>
            <dd>{{ detail[column] || '—' }}</dd>
          </template>
        </dl>
        <div class="row-actions">
          <button
            v-for="action in actions"
            :key="action"
            :class="['link', { disabled: !canRun(detail, action) }]"
            type="button"
            @click="runAction(action, detail, afterDetailAction)"
          >
            {{ action }}
          </button>
        </div>
        <p v-if="detailMessage" :class="['modal-tip', detailOk ? 'ok' : '']">{{ detailMessage }}</p>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | string[] | null>

const ENDPOINT = '/api/truck'
const columns = ["调度单号", "集卡牌号", "司机姓名", "作业任务", "派车时间", "返回时间", "所属车队", "调度状态"]
const actions = ["确认派车", "确认返回", "取消调度"]
const stats = [{"label": "待派车任务", "value": 0}, {"label": "作业中集卡", "value": 0}, {"label": "今日派车次数", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const detail = ref<Row | null>(null)
const detailMessage = ref('')
const detailOk = ref(false)
const lastOk = ref(false)

function canRun(row: Row, action: string): boolean {
  const allowed = row['可执行动作']
  return Array.isArray(allowed) && allowed.includes(action)
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '集卡登记入口尚未接入审批流'
}

async function openDetail(row: Row) {
  detailMessage.value = ''
  detailOk.value = false
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('集卡明细读取失败')
    }
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '集卡明细读取失败'
  }
}

function closeDetail() {
  detail.value = null
  detailMessage.value = ''
  detailOk.value = false
}

async function afterListAction(message: string, ok: boolean) {
  errorMessage.value = message
  lastOk.value = ok
  if (ok) {
    await reload()
    errorMessage.value = message
    lastOk.value = ok
  }
}

async function afterDetailAction(message: string, ok: boolean) {
  detailMessage.value = message
  detailOk.value = ok
  if (ok) {
    await reload()
    if (detail.value) {
      const response = await request(`${ENDPOINT}/${detail.value.id}`)
      if (response.ok) {
        detail.value = await response.json()
      }
    }
  }
}

async function runAction(
  action: string,
  row: Row,
  after: (message: string, ok: boolean) => Promise<void> | void,
) {
  errorMessage.value = ''
  detailMessage.value = ''
  lastOk.value = false
  detailOk.value = false
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    // 放行与拦下都以后端统一判定返回的 message 为准，列表和详情看到同一句说明。
    const payload = (await response.json().catch(() => null)) as
      | { ok?: boolean; message?: string }
      | null
    const ok = Boolean(response.ok && payload?.ok)
    const message = payload?.message || '集卡调度动作未生效，请稍后重试'
    await after(message, ok)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '集卡调度操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  lastOk.value = false
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('集卡列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '集卡调度列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal-card {
  width: 560px;
  max-width: calc(100vw - 32px);
  background: #fff;
  border-radius: 10px;
  padding: 16px 20px;
}
.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.modal-head h3 { margin: 0; font-size: 16px; }
.detail-grid {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 6px 12px;
  margin: 0 0 14px;
  font-size: 13px;
}
.detail-grid dt { color: var(--muted); }
.detail-grid dd { margin: 0; }
.modal-tip { margin: 10px 0 0; font-size: 12px; color: #b42318; }
.modal-tip.ok { color: #15803d; }
.info-text { color: #15803d; }
.link.disabled { color: #9aa6b2; cursor: not-allowed; }
</style>
