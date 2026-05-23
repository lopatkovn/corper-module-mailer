<script setup lang="ts">
import { ref, computed, onMounted, onUpdated, nextTick, watch } from 'vue'
import { usePortal } from '../composables/usePortal'
import { api } from '../api'
import PageHeader from '../components/PageHeader.vue'
import PrimaryBtn from '../components/PrimaryBtn.vue'
import RuleDetailPanel from './RuleDetailPanel.vue'

declare const feather: any

defineProps<{ tabs: any[]; activeTab: string }>()
const emit = defineEmits<{
  (e: 'switch-tab', id: string): void
  (e: 'count', n: number): void
}>()

const { canManage } = usePortal()

interface EventType { id: number; key: string; label: string; source_module: string }
interface Rule {
  id: number; event_type_id: number; channel_id: number;
  recipients: any; is_enabled: boolean; priority: number
}
interface ChannelMini { id: number; kind: string; label: string }

const rules = ref<Rule[]>([])
const eventTypes = ref<EventType[]>([])
const channels = ref<ChannelMini[]>([])
const groups = ref<{ id: number; chat_id: number; title: string }[]>([])
const loading = ref(true)
const search = ref('')
const selectedId = ref<number | null>(null)
const isNewMode = ref(false)

async function load() {
  loading.value = true
  try {
    const [rs, ets, gs, em, tg] = await Promise.all([
      api.get('/api/mailer/rules').then(r => r.data),
      api.get('/api/mailer/event-types').then(r => r.data),
      api.get('/api/mailer/groups').then(r => r.data),
      api.get('/api/mailer/channels/email').then(r => r.data),
      api.get('/api/mailer/channels/telegram').then(r => r.data),
    ])
    rules.value = rs
    eventTypes.value = ets
    groups.value = gs
    const cs: ChannelMini[] = []
    if (em.id) cs.push({ id: em.id, kind: em.kind, label: em.label || 'Email' })
    if (tg.id) cs.push({ id: tg.id, kind: tg.kind, label: tg.label || 'Telegram' })
    channels.value = cs
    emit('count', rules.value.length)
  } finally {
    loading.value = false
    nextTick(() => feather?.replace())
  }
}

function eventTypeLabel(id: number) { return eventTypes.value.find(e => e.id === id)?.label || `#${id}` }
function eventTypeKey(id: number) { return eventTypes.value.find(e => e.id === id)?.key || '' }
function channelInfo(id: number) { return channels.value.find(c => c.id === id) }
function channelKind(id: number) { return channelInfo(id)?.kind || '' }
function channelLabel(id: number) {
  const c = channelInfo(id)
  return c ? (c.label || (c.kind === 'email' ? 'Email' : 'Telegram')) : `#${id}`
}
function channelIcon(id: number) { return channelKind(id) === 'email' ? 'mail' : 'send' }

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return rules.value
  return rules.value.filter(r => {
    const blob = `${eventTypeLabel(r.event_type_id)} ${eventTypeKey(r.event_type_id)} ${channelLabel(r.channel_id)}`.toLowerCase()
    return blob.includes(q)
  })
})

const _PALETTE = ['#E8A66B', '#C9A2D7', '#94B8D9', '#A8C9A3', '#7FB8B0', '#4DBFA6', '#7B6FE0']
function dotFor(s: string): string {
  let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return _PALETTE[h % _PALETTE.length]
}

function summarizeRecipients(r: any): string {
  const parts: string[] = []
  if (r?.emails?.length) parts.push(`${r.emails.length} email`)
  if (r?.employee_ids?.length) parts.push(`${r.employee_ids.length} сотр`)
  if (r?.branch_ids?.length) parts.push(`${r.branch_ids.length} фил`)
  if (r?.telegram_group_ids?.length) parts.push(`${r.telegram_group_ids.length} ТГ`)
  return parts.join(' · ') || 'нет получателей'
}

function selectRule(id: number | null) {
  selectedId.value = id
  isNewMode.value = false
}
const selectedRule = computed(() => rules.value.find(r => r.id === selectedId.value) || null)

function openNew() { selectedId.value = null; isNewMode.value = true }
function closePanel() { selectedId.value = null; isNewMode.value = false }

async function onSaved(rule: Rule) {
  await load()
  selectRule(rule.id)
}
async function onDeleted() {
  closePanel()
  await load()
}

onMounted(load)
onUpdated(() => nextTick(() => feather?.replace()))
</script>

<template>
  <div class="page">
    <div class="page__main">
      <PageHeader
        title="Служба рассылок"
        :count="loading ? '' : `${filtered.length} из ${rules.length}`"
        :tabs="tabs"
        :active-tab="activeTab"
        :search="search"
        search-placeholder="Поиск по событию или каналу"
        @tab="(id: string) => emit('switch-tab', id)"
        @update:search="(v: string) => search = v"
      >
        <template #primary>
          <PrimaryBtn :disabled="!canManage() || !channels.length" @click="openNew">Добавить правило</PrimaryBtn>
        </template>
      </PageHeader>

      <div v-if="loading" class="page__empty">Загрузка…</div>
      <div v-else-if="!channels.length" class="page__empty">
        <div class="page__empty-title">Нет каналов</div>
        <div class="page__empty-hint">Прежде чем создавать правила, настройте хотя бы один канал на вкладке «Каналы».</div>
      </div>
      <div v-else-if="!eventTypes.length" class="page__empty">
        <div class="page__empty-title">Каталог событий пуст</div>
        <div class="page__empty-hint">
          Каталог автоматически наполняется при деплое модулей-источников
          (через <code>module.json.emits</code>). Пока он пуст, правила создавать не на что —
          в журнале появятся записи как только модули начнут публиковать события.
        </div>
      </div>
      <div v-else-if="!rules.length" class="page__empty">
        <div class="page__empty-title">Правил ещё нет</div>
        <div class="page__empty-hint">Нажмите <strong>«Добавить правило»</strong> вверху — выберите событие, канал и получателей.</div>
      </div>
      <div v-else-if="!filtered.length" class="page__empty">Ничего не найдено</div>

      <div v-else class="page__grid">
        <button
          v-for="r in filtered" :key="r.id"
          :class="['ru-card',
                   { 'ru-card--selected': r.id === selectedId,
                     'ru-card--off': !r.is_enabled }]"
          @click="selectRule(r.id)"
        >
          <div class="ru-card__head">
            <span class="ru-card__dot-wrap" :style="{ background: dotFor(eventTypeKey(r.event_type_id)) + '25' }">
              <span class="ru-card__dot" :style="{ background: dotFor(eventTypeKey(r.event_type_id)) }"></span>
            </span>
            <div class="ru-card__roles">
              <span class="ru-card__role" :title="channelKind(r.channel_id) === 'email' ? 'Email' : 'Telegram'">
                <i :data-feather="channelIcon(r.channel_id)"></i>
              </span>
              <span v-if="!r.is_enabled" class="ru-card__role" title="Выключено">
                <i data-feather="pause"></i>
              </span>
            </div>
            <span class="ru-card__count">P {{ r.priority }}</span>
          </div>

          <div class="ru-card__name">{{ eventTypeLabel(r.event_type_id) }}</div>
          <div class="ru-card__key">{{ eventTypeKey(r.event_type_id) }}</div>

          <div class="ru-card__meta">
            <div class="ru-card__meta-row">
              <i :data-feather="channelIcon(r.channel_id)"></i>
              <span>{{ channelLabel(r.channel_id) }}</span>
            </div>
            <div class="ru-card__meta-row">
              <i data-feather="users"></i>
              <span>{{ summarizeRecipients(r.recipients) }}</span>
            </div>
          </div>

          <div class="ru-card__footer">
            <span :class="['badge', r.is_enabled ? 'badge--status-active' : 'badge--status-former']">
              {{ r.is_enabled ? 'включено' : 'выключено' }}
            </span>
            <i data-feather="chevron-right"></i>
          </div>
        </button>
      </div>
    </div>

    <RuleDetailPanel
      v-if="selectedRule || isNewMode"
      :rule="selectedRule"
      :is-new="isNewMode"
      :event-types="eventTypes"
      :channels="channels"
      :groups="groups"
      :can-manage="canManage()"
      @close="closePanel"
      @saved="onSaved"
      @deleted="onDeleted"
    />
  </div>
</template>

<style scoped>
.page { display: flex; height: 100%; min-height: 100vh; background: var(--bg); }
.page__main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; }
.page__empty {
  color: var(--text-4); text-align: center; padding: 60px 32px; font-size: 13px;
}
.page__empty-title { font-size: 14px; color: var(--text-2); margin-bottom: 6px; }
.page__empty-hint {
  font-size: 13px; color: var(--text-3); line-height: 1.6;
  max-width: 540px; margin: 0 auto;
}
.page__empty-hint code { font-family: 'JetBrains Mono', monospace; color: var(--text); background: var(--panel); padding: 1px 6px; border-radius: 4px; }
.page__empty-hint strong { color: var(--text); }

.page__grid {
  flex: 1; overflow: auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
  padding: 18px 32px 32px;
}

.ru-card {
  background: var(--surface);
  border: 1px solid var(--border-2);
  border-radius: 12px;
  padding: 14px 14px 12px;
  cursor: pointer; text-align: left;
  display: flex; flex-direction: column; gap: 8px;
  font-family: inherit;
  transition: border-color .12s, box-shadow .12s;
}
.ru-card:hover { border-color: var(--border-strong); }
.ru-card--selected { border-color: var(--accent); box-shadow: 0 0 0 3px var(--ring); }
.ru-card--off { opacity: .65; }

.ru-card__head { display: flex; justify-content: space-between; align-items: center; }
.ru-card__dot-wrap {
  width: 18px; height: 18px; border-radius: 5px;
  display: flex; align-items: center; justify-content: center;
}
.ru-card__dot { width: 6px; height: 6px; border-radius: 50%; }
.ru-card__roles { display: flex; align-items: center; gap: 4px; margin-right: auto; margin-left: 8px; }
.ru-card__role {
  width: 18px; height: 18px; border-radius: 5px;
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--panel); color: var(--text-3);
}
.ru-card__role :deep(svg) { width: 11px; height: 11px; }
.ru-card__count {
  font-size: 10px; font-family: 'JetBrains Mono', monospace;
  color: var(--text-4); letter-spacing: .06em;
}

.ru-card__name {
  font-size: 15px; font-weight: 600; letter-spacing: -0.01em;
  color: var(--text); word-break: break-word;
}
.ru-card__key {
  font-family: 'JetBrains Mono', monospace; font-size: 11px;
  color: var(--text-4); word-break: break-all;
  margin-top: -4px;
}

.ru-card__meta { display: flex; flex-direction: column; gap: 5px; margin-top: 2px; }
.ru-card__meta-row {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--text-2); line-height: 1.4;
}
.ru-card__meta-row :deep(svg) { width: 12px; height: 12px; color: var(--text-4); flex-shrink: 0; }

.ru-card__footer {
  padding-top: 8px; border-top: 1px dashed var(--border-2);
  display: flex; justify-content: space-between; align-items: center;
}
.ru-card__footer :deep(svg) { width: 12px; height: 12px; color: var(--text-4); }

.badge {
  display: inline-flex; align-items: center;
  font-size: 11px; font-weight: 500; padding: 3px 8px; border-radius: 5px;
}
.badge--status-active { background: var(--status-active-bg); color: var(--status-active-fg); }
.badge--status-former { background: var(--panel); color: var(--text-3); }
</style>
