<script setup lang="ts">
import { ref, computed, onMounted, onUpdated, nextTick, watch } from 'vue'
import { usePortal } from '../composables/usePortal'
import { api } from '../api'
import PageHeader from '../components/PageHeader.vue'
import ChannelDetailPanel from './ChannelDetailPanel.vue'

declare const feather: any

defineProps<{
  tabs: any[]
  activeTab: string
}>()
const emit = defineEmits<{
  (e: 'switch-tab', id: string): void
  (e: 'count', n: number): void
}>()

const { canManage } = usePortal()

interface ChannelPub {
  kind: 'email' | 'telegram' | string
  is_enabled: boolean
  label: string
  status: 'ok' | 'untested' | 'error' | 'unconfigured' | string
  last_test_at: string | null
}
interface ChannelFull {
  id?: number
  kind: string
  is_enabled: boolean
  label: string
  config: any
  last_test_at: string | null
  last_test_ok: boolean | null
  last_test_error: string | null
}

const list = ref<ChannelPub[]>([])
const fullByKind = ref<Record<string, ChannelFull>>({})
const loading = ref(true)
const selectedKind = ref<string | null>(null)

async function load() {
  loading.value = true
  try {
    const [pub, em, tg] = await Promise.all([
      api.get('/api/mailer/channels').then(r => r.data),
      api.get('/api/mailer/channels/email').then(r => r.data),
      api.get('/api/mailer/channels/telegram').then(r => r.data),
    ])
    list.value = pub
    fullByKind.value = { email: em, telegram: tg }
    emit('count', pub.filter((c: ChannelPub) => c.is_enabled).length)
  } finally {
    loading.value = false
    nextTick(() => feather?.replace())
  }
}

function dotColor(kind: string): string {
  return kind === 'email' ? '#7B6FE0' : '#4DBFA6'
}
function iconFor(kind: string): string {
  return kind === 'email' ? 'mail' : 'send'
}
function kindLabel(kind: string): string {
  return kind === 'email' ? 'Email · SMTP' : kind === 'telegram' ? 'Telegram · Bot' : kind
}
function fmtDate(d: string | null): string {
  return d ? new Date(d).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '—'
}
function statusBadge(status: string): { variant: string; label: string } {
  const map: Record<string, { variant: string; label: string }> = {
    ok:           { variant: 'status-active', label: 'Готов' },
    untested:     { variant: 'role',          label: 'Не проверен' },
    error:        { variant: 'status-error',  label: 'Ошибка' },
    unconfigured: { variant: 'status-former', label: 'Не настроен' },
  }
  return map[status] || { variant: 'neutral', label: status }
}

const selectedChannel = computed(() =>
  selectedKind.value ? fullByKind.value[selectedKind.value] : null
)
function selectKind(k: string | null) { selectedKind.value = k }

onMounted(load)
onUpdated(() => nextTick(() => feather?.replace()))
</script>

<template>
  <div class="page">
    <div class="page__main">
      <PageHeader
        title="Служба рассылок"
        :tabs="tabs"
        :active-tab="activeTab"
        @tab="(id: string) => emit('switch-tab', id)"
      />

      <div v-if="loading" class="page__empty">Загрузка…</div>
      <div v-else class="page__grid">
        <button
          v-for="c in list" :key="c.kind"
          :class="['ch-card',
                   { 'ch-card--selected': c.kind === selectedKind,
                     'ch-card--off': !c.is_enabled }]"
          @click="selectKind(c.kind)"
        >
          <div class="ch-card__head">
            <span class="ch-card__dot-wrap" :style="{ background: dotColor(c.kind) + '25' }">
              <span class="ch-card__dot" :style="{ background: dotColor(c.kind) }"></span>
            </span>
            <div class="ch-card__roles">
              <span class="ch-card__role" :title="kindLabel(c.kind)">
                <i :data-feather="iconFor(c.kind)"></i>
              </span>
            </div>
            <span :class="['badge', `badge--${statusBadge(c.status).variant}`]">
              {{ statusBadge(c.status).label }}
            </span>
          </div>

          <div class="ch-card__name">{{ c.label || kindLabel(c.kind) }}</div>

          <div class="ch-card__meta">
            <div class="ch-card__meta-row">
              <i :data-feather="c.is_enabled ? 'check-circle' : 'circle'"></i>
              <span>{{ c.is_enabled ? 'Канал включён' : 'Канал выключен' }}</span>
            </div>
            <div class="ch-card__meta-row">
              <i data-feather="clock"></i>
              <span>{{ c.last_test_at ? 'Проверен ' + fmtDate(c.last_test_at) : 'Не проверялся' }}</span>
            </div>
          </div>

          <div class="ch-card__footer">
            <span>{{ c.kind === 'email' ? 'SMTP-конфигурация' : 'Бот компании' }}</span>
            <i data-feather="chevron-right"></i>
          </div>
        </button>
      </div>
    </div>

    <ChannelDetailPanel
      v-if="selectedChannel"
      :channel="selectedChannel"
      :can-manage="canManage()"
      @close="selectKind(null)"
      @updated="load"
    />
  </div>
</template>

<style scoped>
.page {
  display: flex;
  height: 100%;
  min-height: 100vh;
  background: var(--bg);
}
.page__main {
  flex: 1;
  min-width: 0;
  display: flex; flex-direction: column;
  overflow: hidden;
}
.page__empty {
  color: var(--text-4);
  text-align: center;
  padding: 60px 32px;
  font-size: 13px;
}

.page__grid {
  flex: 1;
  overflow: auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
  padding: 18px 32px 32px;
}

.ch-card {
  background: var(--surface);
  border: 1px solid var(--border-2);
  border-radius: 12px;
  padding: 14px 14px 12px;
  cursor: pointer;
  text-align: left;
  display: flex; flex-direction: column; gap: 10px;
  font-family: inherit;
  transition: border-color .12s, box-shadow .12s;
}
.ch-card:hover { border-color: var(--border-strong); }
.ch-card--selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--ring);
}
.ch-card--off { opacity: .85; }

.ch-card__head {
  display: flex; justify-content: space-between; align-items: center;
}
.ch-card__dot-wrap {
  width: 18px; height: 18px;
  border-radius: 5px;
  display: flex; align-items: center; justify-content: center;
}
.ch-card__dot { width: 6px; height: 6px; border-radius: 50%; }
.ch-card__roles {
  display: flex; align-items: center; gap: 4px;
  margin-right: auto; margin-left: 8px;
}
.ch-card__role {
  width: 18px; height: 18px;
  border-radius: 5px;
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--panel);
  color: var(--text-3);
}
.ch-card__role :deep(svg) { width: 11px; height: 11px; }

.ch-card__name {
  font-size: 15px; font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--text);
  word-break: break-word;
}

.ch-card__meta {
  display: flex; flex-direction: column; gap: 5px;
  margin-top: auto;
}
.ch-card__meta-row {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--text-2);
  line-height: 1.4;
}
.ch-card__meta-row :deep(svg) { width: 12px; height: 12px; color: var(--text-4); flex-shrink: 0; }

.ch-card__footer {
  padding-top: 8px;
  border-top: 1px dashed var(--border-2);
  font-size: 11px;
  color: var(--text-4);
  display: flex; justify-content: space-between; align-items: center;
}
.ch-card__footer :deep(svg) { width: 12px; height: 12px; }

/* Локальные badge-варианты для error (status-active/former/role уже есть в shell Badge) */
.badge {
  display: inline-flex; align-items: center;
  font-size: 11px; font-weight: 500;
  padding: 3px 8px;
  border-radius: 5px;
  white-space: nowrap;
}
.badge--status-active { background: var(--status-active-bg); color: var(--status-active-fg); }
.badge--status-former { background: var(--panel); color: var(--text-3); }
.badge--role          { background: var(--role-bg); color: var(--role-fg); }
.badge--neutral       { background: var(--panel); color: var(--text-2); }
.badge--status-error  { background: #fbe8e7; color: #b3261e; }
</style>
