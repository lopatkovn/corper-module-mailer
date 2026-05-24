<script setup lang="ts">
import { ref, computed, onMounted, onUpdated, nextTick } from 'vue'
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

const { canManage, branches } = usePortal()

interface EventType { id: number; key: string; label: string; source_module: string }
interface Group { id: number; chat_id: number; title: string; is_forum: boolean }
interface Topic { id: number; telegram_thread_id: number; name: string }
interface Rule {
  id: number
  event_type_id: number
  branch_id: number | null
  telegram_group_id: number
  topic_id: number | null
  is_enabled: boolean
  priority: number
}

const rules = ref<Rule[]>([])
const eventTypes = ref<EventType[]>([])
const groups = ref<Group[]>([])
const topicsByGroup = ref<Record<number, Topic[]>>({})
const loading = ref(true)
const search = ref('')
const selectedId = ref<number | null>(null)
const isNewMode = ref(false)

async function load() {
  loading.value = true
  try {
    const [rs, ets, gs] = await Promise.all([
      api.get('/api/mailer/rules').then(r => r.data),
      api.get('/api/mailer/event-types').then(r => r.data),
      api.get('/api/mailer/groups').then(r => r.data),
    ])
    rules.value = rs
    eventTypes.value = ets
    groups.value = gs
    const tmap: Record<number, Topic[]> = {}
    await Promise.all(groups.value.map(async g => {
      try {
        tmap[g.id] = await api.get(`/api/mailer/groups/${g.id}/topics`).then(r => r.data)
      } catch { tmap[g.id] = [] }
    }))
    topicsByGroup.value = tmap
    emit('count', rs.length)
  } finally {
    loading.value = false
    nextTick(() => feather?.replace())
  }
}

function eventTypeLabel(id: number) { return eventTypes.value.find(e => e.id === id)?.label || `#${id}` }
function eventTypeKey(id: number) { return eventTypes.value.find(e => e.id === id)?.key || '' }
function groupTitle(id: number) {
  const g = groups.value.find(g => g.id === id)
  return g ? (g.title || `chat ${g.chat_id}`) : `#${id}`
}
function topicName(gid: number, tid: number | null) {
  if (!tid) return ''
  const t = (topicsByGroup.value[gid] || []).find(t => t.id === tid)
  return t ? t.name : `#${tid}`
}
function branchName(bid: number | null) {
  if (!bid) return ''
  return branches.value.find(b => b.id === bid)?.name || `#${bid}`
}

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return rules.value
  return rules.value.filter(r => {
    const blob = `${eventTypeLabel(r.event_type_id)} ${eventTypeKey(r.event_type_id)} ${groupTitle(r.telegram_group_id)} ${branchName(r.branch_id)}`.toLowerCase()
    return blob.includes(q)
  })
})

const _PAL = ['#E8A66B', '#C9A2D7', '#94B8D9', '#A8C9A3', '#7FB8B0', '#4DBFA6', '#7B6FE0']
function dotFor(s: string): string {
  let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return _PAL[h % _PAL.length]
}

function selectRule(id: number | null) { selectedId.value = id; isNewMode.value = false }
const selectedRule = computed(() => rules.value.find(r => r.id === selectedId.value) || null)

function openNew() { selectedId.value = null; isNewMode.value = true }
function closePanel() { selectedId.value = null; isNewMode.value = false }

async function onSaved(rule: Rule) { await load(); selectRule(rule.id) }
async function onDeleted() { closePanel(); await load() }

const noChannel = computed(() => groups.value.length === 0)

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
        search-placeholder="Поиск по событию, группе или филиалу"
        @tab="(id: string) => emit('switch-tab', id)"
        @update:search="(v: string) => search = v"
      >
        <template #primary>
          <PrimaryBtn :disabled="!canManage() || noChannel || !eventTypes.length" @click="openNew">Добавить правило</PrimaryBtn>
        </template>
      </PageHeader>

      <div v-if="loading" class="page__empty">Загрузка…</div>
      <div v-else-if="noChannel" class="page__empty">
        <div class="page__empty-title">Сначала настройте Telegram</div>
        <div class="page__empty-hint">
          Правила направляют события в Telegram-группы/топики. Откройте вкладку
          <strong>Каналы</strong>, задайте бота, пригласите его в нужный чат —
          после этого здесь появится возможность создавать правила.
        </div>
      </div>
      <div v-else-if="!eventTypes.length" class="page__empty">
        <div class="page__empty-title">Каталог событий пуст</div>
        <div class="page__empty-hint">
          Каталог наполняется автоматически при деплое модулей с
          <code>emits</code> в <code>module.json</code>. Пока он пуст —
          правила создавать не на что.
        </div>
      </div>
      <div v-else-if="!rules.length" class="page__empty">
        <div class="page__empty-title">Правил ещё нет</div>
        <div class="page__empty-hint">Нажмите <strong>«Добавить правило»</strong> — выберите событие, целевую группу и (опционально) топик.</div>
      </div>
      <div v-else-if="!filtered.length" class="page__empty">Ничего не найдено</div>

      <div v-else class="page__grid">
        <button
          v-for="r in filtered" :key="r.id"
          :class="['ru-card', { 'ru-card--selected': r.id === selectedId, 'ru-card--off': !r.is_enabled }]"
          @click="selectRule(r.id)"
        >
          <div class="ru-card__head">
            <span class="ru-card__dot-wrap" :style="{ background: dotFor(eventTypeKey(r.event_type_id)) + '25' }">
              <span class="ru-card__dot" :style="{ background: dotFor(eventTypeKey(r.event_type_id)) }"></span>
            </span>
            <div class="ru-card__roles">
              <span class="ru-card__role" title="Telegram"><i data-feather="send"></i></span>
              <span v-if="r.branch_id" class="ru-card__role" title="Фильтр по филиалу"><i data-feather="map-pin"></i></span>
              <span v-if="r.topic_id" class="ru-card__role" title="Конкретный топик"><i data-feather="hash"></i></span>
              <span v-if="!r.is_enabled" class="ru-card__role" title="Выключено"><i data-feather="pause"></i></span>
            </div>
            <span class="ru-card__count">P {{ r.priority }}</span>
          </div>

          <div class="ru-card__name">{{ eventTypeLabel(r.event_type_id) }}</div>
          <div class="ru-card__key">{{ eventTypeKey(r.event_type_id) }}</div>

          <div class="ru-card__meta">
            <div class="ru-card__meta-row">
              <i data-feather="map-pin"></i>
              <span :class="{ 'ru-card__muted': !r.branch_id }">
                {{ r.branch_id ? branchName(r.branch_id) : 'любой филиал' }}
              </span>
            </div>
            <div class="ru-card__meta-row">
              <i data-feather="message-square"></i>
              <span>{{ groupTitle(r.telegram_group_id) }}</span>
            </div>
            <div v-if="r.topic_id" class="ru-card__meta-row">
              <i data-feather="hash"></i>
              <span>{{ topicName(r.telegram_group_id, r.topic_id) }}</span>
            </div>
            <div v-else class="ru-card__meta-row ru-card__muted">
              <i data-feather="hash"></i>
              <span>общий чат (без топика)</span>
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
      :groups="groups"
      :topics-by-group="topicsByGroup"
      :can-manage="canManage()"
      @close="closePanel"
      @saved="onSaved"
      @deleted="onDeleted"
      @topics-reloaded="load"
    />
  </div>
</template>

<style scoped>
.page { display: flex; height: 100%; min-height: 100vh; background: var(--bg); }
.page__main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; }
.page__empty { color: var(--text-4); text-align: center; padding: 60px 32px; font-size: 13px; }
.page__empty-title { font-size: 14px; color: var(--text-2); margin-bottom: 6px; }
.page__empty-hint { font-size: 13px; color: var(--text-3); line-height: 1.6; max-width: 540px; margin: 0 auto; }
.page__empty-hint code { font-family: 'JetBrains Mono', monospace; color: var(--text); background: var(--panel); padding: 1px 6px; border-radius: 4px; }
.page__empty-hint strong { color: var(--text); }

.page__grid {
  flex: 1; overflow: auto;
  display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px; padding: 18px 32px 32px;
}

.ru-card {
  background: var(--surface); border: 1px solid var(--border-2);
  border-radius: 12px; padding: 14px 14px 12px;
  cursor: pointer; text-align: left;
  display: flex; flex-direction: column; gap: 8px;
  font-family: inherit;
  transition: border-color .12s, box-shadow .12s;
}
.ru-card:hover { border-color: var(--border-strong); }
.ru-card--selected { border-color: var(--accent); box-shadow: 0 0 0 3px var(--ring); }
.ru-card--off { opacity: .65; }

.ru-card__head { display: flex; justify-content: space-between; align-items: center; }
.ru-card__dot-wrap { width: 18px; height: 18px; border-radius: 5px; display: flex; align-items: center; justify-content: center; }
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
  color: var(--text-4); word-break: break-all; margin-top: -4px;
}

.ru-card__meta { display: flex; flex-direction: column; gap: 5px; margin-top: 2px; }
.ru-card__meta-row {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--text-2); line-height: 1.4;
}
.ru-card__meta-row :deep(svg) { width: 12px; height: 12px; color: var(--text-4); flex-shrink: 0; }
.ru-card__muted { color: var(--placeholder); }

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
