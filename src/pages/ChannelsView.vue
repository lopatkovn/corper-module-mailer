<script setup lang="ts">
import { ref, computed, onMounted, onUpdated, nextTick, watch } from 'vue'
import { usePortal } from '../composables/usePortal'
import { api } from '../api'
import PageHeader from '../components/PageHeader.vue'
import ChannelDetailPanel from './ChannelDetailPanel.vue'

const INTRO_KEY = 'mailer_channels_intro_dismissed'

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

const introDismissed = ref(localStorage.getItem(INTRO_KEY) === '1')
function dismissIntro() {
  introDismissed.value = true
  localStorage.setItem(INTRO_KEY, '1')
}

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

      <div v-if="!introDismissed" class="ch-intro">
        <div class="ch-intro__icon"><i data-feather="send"></i></div>
        <div class="ch-intro__body">
          <div class="ch-intro__title">Что такое канал доставки?</div>
          <div class="ch-intro__text">
            Канал — способ, которым модули портала отправляют уведомления и
            письма пользователям. Все доставки идут через mailer-worker, а вы
            настраиваете каналы централизованно для всей компании.
          </div>
          <ul class="ch-intro__list">
            <li><strong>Email · SMTP</strong> — сервер исходящей почты компании (письма активации, отчёты, восстановление пароля)</li>
            <li><strong>Telegram · Bot</strong> — бот компании для рассылок в чаты/группы сотрудников</li>
            <li><strong>Правила</strong> привязывают типы событий (просрочка задачи, новый пользователь, …) к каналу и получателям</li>
            <li><strong>Журнал</strong> хранит историю всех отправок и входящих сообщений из Telegram</li>
          </ul>
          <div class="ch-intro__hint">
            Модули видят список настроенных каналов через
            <code>GET /api/mailer/channels</code> и предлагают пользователю
            доступные способы доставки (например, «Пользователи» — какие
            методы регистрации показывать).
          </div>
        </div>
        <button class="ch-intro__close" @click="dismissIntro" title="Скрыть">
          <i data-feather="x"></i>
        </button>
      </div>

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

/* Intro hint — клон BranchesPage.branches-intro */
.ch-intro {
  display: flex;
  gap: 14px;
  padding: 14px 16px;
  margin: 18px 32px 4px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  position: relative;
}
.ch-intro__icon {
  flex-shrink: 0;
  width: 36px; height: 36px;
  border-radius: 9px;
  background: var(--surface);
  border: 1px solid var(--border);
  display: flex; align-items: center; justify-content: center;
  color: var(--accent);
}
.ch-intro__icon :deep(svg), .ch-intro__icon i { width: 16px; height: 16px; }
.ch-intro__body { flex: 1; min-width: 0; }
.ch-intro__title {
  font-size: 13px; font-weight: 600;
  color: var(--text);
  margin-bottom: 4px;
}
.ch-intro__text {
  font-size: 12px; color: var(--text-2);
  line-height: 1.5; margin-bottom: 6px;
}
.ch-intro__list {
  margin: 0 0 6px;
  padding-left: 18px;
  font-size: 12px;
  color: var(--text-2);
  line-height: 1.55;
}
.ch-intro__list strong { color: var(--text); font-weight: 600; }
.ch-intro__hint {
  font-size: 11px; color: var(--text-3);
  margin-top: 4px;
  padding-top: 6px;
  border-top: 1px dashed var(--border);
}
.ch-intro__hint code {
  font-family: 'JetBrains Mono', monospace;
  background: var(--surface);
  border: 1px solid var(--border);
  padding: 1px 5px;
  border-radius: 4px;
  color: var(--text);
}
.ch-intro__close {
  position: absolute;
  top: 8px; right: 8px;
  width: 26px; height: 26px;
  border-radius: 7px;
  border: 0;
  background: transparent;
  color: var(--text-4);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: background .12s, color .12s;
}
.ch-intro__close :deep(svg), .ch-intro__close i { width: 13px; height: 13px; }
.ch-intro__close:hover { background: var(--hover-bg); color: var(--text); }

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
