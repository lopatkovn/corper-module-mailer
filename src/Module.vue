<script setup lang="ts">
import { ref, defineAsyncComponent, onMounted, onUpdated, nextTick } from 'vue'
import { usePortal } from './composables/usePortal'
import ExamplePage from './pages/ExamplePage.vue'

declare const feather: any

const isDev = import.meta.env.DEV
const DevToolbar = isDev
  ? defineAsyncComponent(() => import('./components/DevToolbar.vue'))
  : null
const { user, company, branches, companyId, loaded, load, canView, canManage } = usePortal()
const activeTab = ref('main')

const tabs = [
  { key: 'main', label: 'Главная' },
]

onMounted(() => load())
onUpdated(() => nextTick(() => { try { feather?.replace() } catch {} }))
</script>

<template>
  <div v-if="!loaded" class="mod-loading">Загрузка...</div>

  <div v-else-if="!canView()" class="mod-denied">
    <div class="mod-denied__icon">&#x1f512;</div>
    <div class="mod-denied__title">Доступ запрещён</div>
    <div class="mod-denied__text">У вас нет прав для просмотра этого модуля.</div>
  </div>

  <div v-else class="mod">
    <div v-if="tabs.length > 1" class="mod-tabs">
      <button
        v-for="t in tabs" :key="t.key"
        :class="['mod-tabs__item', { 'mod-tabs__item--active': activeTab === t.key }]"
        @click="activeTab = t.key"
      >{{ t.label }}</button>
    </div>

    <ExamplePage v-if="activeTab === 'main'" />
  </div>

  <component :is="DevToolbar" v-if="DevToolbar" />
</template>

<style>
body { margin: 0; padding: 16px; font-family: 'Inter', -apple-system, sans-serif; font-size: 14px; color: #1a1a2e; background: #f8f9fb; }

.mod-loading { display: flex; align-items: center; justify-content: center; padding: 60px; color: #8b8fa3; }
.mod-denied { display: flex; flex-direction: column; align-items: center; padding: 80px 20px; text-align: center; }
.mod-denied__icon { font-size: 48px; margin-bottom: 16px; }
.mod-denied__title { font-size: 18px; font-weight: 700; color: #1a1a2e; margin-bottom: 8px; }
.mod-denied__text { font-size: 14px; color: #8b8fa3; }

.mod-tabs { display: flex; gap: 2px; background: #fff; border-radius: 12px; padding: 4px; margin-bottom: 16px; border: 1px solid #f0f0f0; }
.mod-tabs__item { flex: 1; padding: 9px 14px; border: none; background: transparent; border-radius: 8px; font-size: 13px; font-weight: 500; color: #8b8fa3; cursor: pointer; transition: all 0.15s; text-align: center; }
.mod-tabs__item:hover { color: #1a1a2e; background: #f5f5f5; }
.mod-tabs__item--active { background: #eef2ff; color: #4338ca; font-weight: 600; }

.mod-card { background: #fff; border: 1px solid #f0f0f0; border-radius: 12px; padding: 20px; margin-bottom: 16px; }
.mod-card__title { font-size: 15px; font-weight: 600; color: #1a1a2e; margin: 0 0 12px; }
.mod-table { width: 100%; border-collapse: collapse; }
.mod-table th { text-align: left; padding: 10px 12px; font-size: 11px; font-weight: 600; color: #8b8fa3; text-transform: uppercase; border-bottom: 1px solid #f0f0f0; }
.mod-table td { padding: 10px 12px; border-bottom: 1px solid #f8f8f8; font-size: 13px; }
.mod-btn { display: inline-flex; align-items: center; gap: 6px; padding: 8px 16px; border-radius: 8px; font-size: 13px; font-weight: 500; border: 1px solid #e5e7eb; color: #374151; background: #fff; cursor: pointer; transition: all 0.15s; }
.mod-btn:hover { background: #f9fafb; }
.mod-btn--primary { background: #4338ca; color: #fff; border-color: #4338ca; }
.mod-btn--primary:hover { background: #3730a3; }
.mod-empty { text-align: center; padding: 40px; color: #9ca3af; font-size: 13px; }
</style>
