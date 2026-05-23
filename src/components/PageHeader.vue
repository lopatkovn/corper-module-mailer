<script setup lang="ts">
import { onUpdated, nextTick } from 'vue'

interface Tab { id: string; label: string; count?: number }

const props = withDefaults(defineProps<{
  title: string
  count?: string | number
  tabs?: Tab[]
  activeTab?: string
  search?: string
  searchPlaceholder?: string
  viewMode?: 'grid' | 'list'
}>(), {
  searchPlaceholder: 'Поиск по имени, email, должности или отделу',
})

const emit = defineEmits<{
  (e: 'tab', id: string): void
  (e: 'update:search', value: string): void
  (e: 'update:viewMode', mode: 'grid' | 'list'): void
}>()

declare const feather: any
onUpdated(() => nextTick(() => feather?.replace()))
</script>

<template>
  <header class="page-header">
    <div class="page-header__top">
      <h1 class="page-header__title">{{ title }}</h1>
      <span v-if="count != null" class="page-header__count">{{ count }}</span>
      <div class="page-header__actions">
        <slot name="extra" />
        <slot name="primary" />
      </div>
    </div>

    <div v-if="tabs || search != null || viewMode" class="page-header__row">
      <div v-if="tabs && tabs.length" class="page-header__tabs">
        <button
          v-for="t in tabs"
          :key="t.id"
          :class="['page-header__tab', { 'page-header__tab--active': activeTab === t.id }]"
          @click="emit('tab', t.id)"
        >
          {{ t.label }}
          <span v-if="t.count != null" class="page-header__tab-count">{{ t.count }}</span>
        </button>
      </div>

      <div v-if="search != null" class="page-header__search">
        <i data-feather="search" class="page-header__search-icon"></i>
        <input
          :value="search"
          :placeholder="searchPlaceholder"
          @input="emit('update:search', ($event.target as HTMLInputElement).value)"
        />
        <span class="page-header__kbd">⌘ K</span>
      </div>

      <div v-if="viewMode" class="page-header__view">
        <button
          :class="['page-header__view-btn', { 'page-header__view-btn--active': viewMode === 'grid' }]"
          title="Карточки"
          @click="emit('update:viewMode', 'grid')"
        ><i data-feather="grid"></i></button>
        <button
          :class="['page-header__view-btn', { 'page-header__view-btn--active': viewMode === 'list' }]"
          title="Таблица"
          @click="emit('update:viewMode', 'list')"
        ><i data-feather="menu"></i></button>
      </div>
    </div>
  </header>
</template>

<style scoped>
.page-header {
  padding: 24px 32px 0;
  display: flex; flex-direction: column;
  gap: 18px;
  flex-shrink: 0;
}
.page-header__top {
  display: flex; align-items: baseline;
  gap: 14px;
}
.page-header__title {
  font-size: 26px; font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--text);
  margin: 0;
}
.page-header__count {
  font-size: 13px; color: var(--text-4);
  font-family: 'JetBrains Mono', monospace;
}
.page-header__actions {
  margin-left: auto;
  display: flex; gap: 10px;
  align-items: center;
}
.page-header__row {
  display: flex; align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.page-header__tabs {
  display: flex; gap: 4px;
  padding: 3px;
  background: var(--panel);
  border-radius: 9px;
  border: 1px solid var(--border);
}
.page-header__tab {
  padding: 7px 14px;
  border: 0; border-radius: 7px;
  cursor: pointer;
  font-size: 13px; font-weight: 500;
  background: transparent;
  color: var(--text-3);
  font-family: inherit;
  transition: background .15s, color .15s, box-shadow .15s;
}
.page-header__tab:hover { color: var(--text); }
.page-header__tab--active {
  background: var(--surface);
  color: var(--text);
  box-shadow: 0 1px 2px var(--ring);
}
.page-header__tab-count {
  margin-left: 6px;
  color: var(--text-4);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}

.page-header__search {
  position: relative;
  flex: 1; min-width: 240px; max-width: 480px;
}
.page-header__search input {
  width: 100%;
  padding: 9px 12px 9px 36px;
  font-size: 13px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface);
  outline: none;
  font-family: inherit;
  color: var(--text);
  transition: border-color .15s, box-shadow .15s;
}
.page-header__search input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--ring);
}
.page-header__search input::placeholder { color: var(--placeholder); }
.page-header__search-icon {
  position: absolute;
  left: 12px; top: 50%;
  transform: translateY(-50%);
  color: var(--text-4);
  width: 15px; height: 15px;
}
.page-header__search-icon :deep(svg) { width: 15px; height: 15px; }
.page-header__kbd {
  position: absolute;
  right: 10px; top: 50%;
  transform: translateY(-50%);
  font-size: 10px;
  font-family: 'JetBrains Mono', monospace;
  color: var(--placeholder);
  background: var(--kbd-bg);
  padding: 1px 6px;
  border-radius: 4px;
}

.page-header__view {
  display: flex; gap: 0;
  background: var(--panel);
  border-radius: 9px;
  border: 1px solid var(--border);
  padding: 3px;
  margin-left: auto;
}
.page-header__view-btn {
  width: 32px; height: 30px;
  border: 0; border-radius: 6px;
  cursor: pointer;
  background: transparent;
  color: var(--text-2);
  display: flex; align-items: center; justify-content: center;
  transition: background .15s;
}
.page-header__view-btn:hover { color: var(--text); }
.page-header__view-btn--active {
  background: var(--surface);
  box-shadow: 0 1px 2px var(--ring);
  color: var(--accent);
}
.page-header__view-btn :deep(svg) { width: 15px; height: 15px; }
</style>
