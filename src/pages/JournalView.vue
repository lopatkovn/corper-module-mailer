<script setup lang="ts">
import { ref, computed, onMounted, onUpdated, nextTick, watch } from 'vue'
import { api } from '../api'
import PageHeader from '../components/PageHeader.vue'
import GhostBtn from '../components/GhostBtn.vue'

declare const feather: any

defineProps<{ tabs: any[]; activeTab: string }>()
const emit = defineEmits<{
  (e: 'switch-tab', id: string): void
  (e: 'count', n: number): void
}>()

interface Message {
  id: number; channel_id: number | null; source_module: string;
  event_type: string; to_address: string; subject: string | null;
  status: string; attempts: number; last_error: string | null;
  sent_at: string | null; created_at: string;
}
interface Inbound {
  id: number; chat_id: number; from_username: string | null;
  text: string | null; reply_to_message_id: number | null;
  created_at: string;
}

const sub = ref<'out' | 'in'>('out')
const messages = ref<Message[]>([])
const inbound = ref<Inbound[]>([])
const statusFilter = ref('')
const kindFilter = ref('')
const search = ref('')
const loading = ref(true)
const expandedId = ref<number | null>(null)

async function load() {
  loading.value = true
  try {
    if (sub.value === 'out') {
      const params: any = { limit: 100 }
      if (statusFilter.value) params.status = statusFilter.value
      if (kindFilter.value) params.kind = kindFilter.value
      const res = await api.get('/api/mailer/messages', { params }).then(r => r.data)
      messages.value = res.items
      // pending count → tab badge
      const pendingCount = res.items.filter((m: Message) => m.status === 'pending' || m.status === 'sending').length
      emit('count', pendingCount)
    } else {
      const res = await api.get('/api/mailer/inbound', { params: { limit: 100 } }).then(r => r.data)
      inbound.value = res.items
    }
  } finally {
    loading.value = false
    nextTick(() => feather?.replace())
  }
}

watch([sub, statusFilter, kindFilter], load)

const filteredMessages = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return messages.value
  return messages.value.filter(m =>
    `${m.to_address} ${m.subject || ''} ${m.event_type} ${m.source_module}`.toLowerCase().includes(q))
})
const filteredInbound = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return inbound.value
  return inbound.value.filter(i =>
    `${i.text || ''} ${i.from_username || ''} ${i.chat_id}`.toLowerCase().includes(q))
})

function statusBadgeVariant(s: string): string {
  return s === 'sent'    ? 'status-active'
       : s === 'failed'  ? 'status-error'
       : 'role' /* pending/sending */
}
function statusLabel(s: string): string {
  return s === 'sent' ? 'отправлено'
       : s === 'failed' ? 'ошибка'
       : s === 'pending' ? 'в очереди'
       : s === 'sending' ? 'отправляется' : s
}

function fmtFull(d: string): string {
  return new Date(d).toLocaleString('ru-RU')
}
function fmtRel(d: string): string {
  const t = new Date(d).getTime(), now = Date.now()
  const sec = Math.floor((now - t) / 1000)
  if (sec < 60)   return `${sec}с назад`
  if (sec < 3600) return `${Math.floor(sec / 60)}м назад`
  if (sec < 86400) return `${Math.floor(sec / 3600)}ч назад`
  return new Date(d).toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' })
}

function toggleExpand(id: number) {
  expandedId.value = expandedId.value === id ? null : id
}

onMounted(load)
onUpdated(() => nextTick(() => feather?.replace()))
</script>

<template>
  <div class="page">
    <div class="page__main">
      <PageHeader
        title="Служба рассылок"
        :count="loading ? '' : (sub === 'out' ? `${filteredMessages.length}` : `${filteredInbound.length}`)"
        :tabs="tabs"
        :active-tab="activeTab"
        :search="search"
        :search-placeholder="sub === 'out' ? 'Поиск по адресу, теме, событию' : 'Поиск по тексту, отправителю, chat_id'"
        @tab="(id: string) => emit('switch-tab', id)"
        @update:search="(v: string) => search = v"
      >
        <template #primary>
          <GhostBtn @click="load" :disabled="loading">
            <i data-feather="refresh-cw"></i>
            Обновить
          </GhostBtn>
        </template>
      </PageHeader>

      <!-- Sub-tabs (исходящие / входящие) + filters -->
      <div class="jr__controls">
        <div class="jr__subtabs">
          <button :class="['jr__subtab', { 'jr__subtab--active': sub === 'out' }]" @click="sub = 'out'">
            <i data-feather="upload"></i>
            Исходящие
          </button>
          <button :class="['jr__subtab', { 'jr__subtab--active': sub === 'in' }]" @click="sub = 'in'">
            <i data-feather="download"></i>
            Входящие
          </button>
        </div>
        <div v-if="sub === 'out'" class="jr__filters">
          <label class="jr__filter">
            <span>Статус</span>
            <select v-model="statusFilter">
              <option value="">Все</option>
              <option value="pending">В очереди</option>
              <option value="sending">Отправляется</option>
              <option value="sent">Отправлено</option>
              <option value="failed">Ошибка</option>
            </select>
          </label>
          <label class="jr__filter">
            <span>Канал</span>
            <select v-model="kindFilter">
              <option value="">Любой</option>
              <option value="email">Email</option>
              <option value="telegram">Telegram</option>
            </select>
          </label>
        </div>
      </div>

      <div v-if="loading" class="page__empty">Загрузка…</div>

      <!-- OUTGOING -->
      <div v-else-if="sub === 'out'" class="jr__body">
        <div v-if="!filteredMessages.length" class="page__empty">
          {{ messages.length ? 'Ничего не найдено' : 'Сообщений ещё нет.' }}
        </div>
        <div v-else class="jr__list">
          <div v-for="m in filteredMessages" :key="m.id"
               :class="['jr-row', `jr-row--${statusBadgeVariant(m.status).split('-').pop()}`]">
            <div class="jr-row__main" @click="toggleExpand(m.id)">
              <div class="jr-row__icon"><i data-feather="mail"></i></div>
              <div class="jr-row__col jr-row__col--main">
                <div class="jr-row__title">{{ m.subject || m.event_type }}</div>
                <div class="jr-row__sub">
                  <code>{{ m.event_type }}</code> · {{ m.source_module }} → {{ m.to_address }}
                </div>
              </div>
              <div class="jr-row__col jr-row__col--time">
                <span :title="fmtFull(m.created_at)">{{ fmtRel(m.created_at) }}</span>
              </div>
              <div class="jr-row__col jr-row__col--status">
                <span :class="['badge', `badge--${statusBadgeVariant(m.status)}`]">{{ statusLabel(m.status) }}</span>
                <span v-if="m.attempts > 1" class="jr-row__attempts">×{{ m.attempts }}</span>
              </div>
              <i :data-feather="expandedId === m.id ? 'chevron-down' : 'chevron-right'" class="jr-row__chev"></i>
            </div>
            <div v-if="expandedId === m.id" class="jr-row__expand">
              <div class="jr-row__exp-grid">
                <div><span>ID</span><code>{{ m.id }}</code></div>
                <div><span>Создано</span><code>{{ fmtFull(m.created_at) }}</code></div>
                <div v-if="m.sent_at"><span>Отправлено</span><code>{{ fmtFull(m.sent_at) }}</code></div>
                <div><span>Попыток</span><code>{{ m.attempts }}</code></div>
              </div>
              <div v-if="m.last_error" class="jr-row__error">
                <i data-feather="alert-circle"></i>
                <span>{{ m.last_error }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- INCOMING -->
      <div v-else class="jr__body">
        <div v-if="!filteredInbound.length" class="page__empty">
          {{ inbound.length ? 'Ничего не найдено' : 'Входящих сообщений ещё нет.' }}
        </div>
        <div v-else class="jr__list">
          <div v-for="i in filteredInbound" :key="i.id" class="jr-row jr-row--in">
            <div class="jr-row__main">
              <div class="jr-row__icon jr-row__icon--in"><i data-feather="send"></i></div>
              <div class="jr-row__col jr-row__col--main">
                <div class="jr-row__title">
                  {{ i.from_username ? '@' + i.from_username : '(аноним)' }}
                  <span class="jr-row__chat">chat <code>{{ i.chat_id }}</code></span>
                </div>
                <div class="jr-row__sub">{{ i.text || '(без текста)' }}</div>
              </div>
              <div class="jr-row__col jr-row__col--time">
                <span :title="fmtFull(i.created_at)">{{ fmtRel(i.created_at) }}</span>
              </div>
              <div class="jr-row__col jr-row__col--status">
                <span v-if="i.reply_to_message_id" class="badge badge--neutral">
                  reply на #{{ i.reply_to_message_id }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  height: 100vh;
  max-height: 100vh;
  overflow: hidden;
  background: var(--bg);
}
.page__main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; }
.page__empty {
  color: var(--text-4); text-align: center; padding: 60px 32px; font-size: 13px;
}

.jr__controls {
  display: flex; align-items: center; gap: 16px;
  padding: 14px 32px 0;
}
.jr__subtabs {
  display: flex; gap: 4px; padding: 3px;
  background: var(--panel); border: 1px solid var(--border); border-radius: 9px;
}
.jr__subtab {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 7px 14px; border: 0; border-radius: 7px;
  background: transparent; color: var(--text-3); cursor: pointer;
  font-size: 13px; font-weight: 500; font-family: inherit;
  transition: background .15s, color .15s;
}
.jr__subtab :deep(svg) { width: 13px; height: 13px; }
.jr__subtab:hover { color: var(--text); }
.jr__subtab--active {
  background: var(--surface); color: var(--text);
  box-shadow: 0 1px 2px var(--ring);
}
.jr__filters { display: flex; gap: 14px; align-items: center; }
.jr__filter { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-3); }
.jr__filter select {
  padding: 6px 9px; font-size: 12px;
  border: 1px solid var(--border); border-radius: 7px;
  background: var(--surface); color: var(--text); font-family: inherit; cursor: pointer;
}
.jr__filter select:focus { outline: 0; border-color: var(--accent); box-shadow: 0 0 0 3px var(--ring); }

.jr__body {
  flex: 1; overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  scrollbar-color: var(--scrollbar, var(--border-strong)) transparent;
  padding: 14px 32px 32px;
}

.jr__list {
  display: flex; flex-direction: column;
  background: var(--surface);
  border: 1px solid var(--border-2);
  border-radius: 12px;
  overflow: hidden;
}

.jr-row {
  border-bottom: 1px solid var(--border-2);
}
.jr-row:last-child { border-bottom: 0; }

.jr-row__main {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 16px;
  cursor: pointer;
  transition: background .12s;
}
.jr-row__main:hover { background: var(--hover-bg); }

.jr-row__icon {
  width: 32px; height: 32px; border-radius: 8px;
  background: var(--panel); color: var(--text-3);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.jr-row__icon :deep(svg) { width: 14px; height: 14px; }
.jr-row--sent .jr-row__icon { background: var(--status-active-bg); color: var(--status-active-fg); }
.jr-row--error .jr-row__icon, .jr-row--failed .jr-row__icon { background: #fbe8e7; color: #b3261e; }
.jr-row__icon--in { background: #ddeaf7; color: #2d4f7a; }

.jr-row__col { min-width: 0; }
.jr-row__col--main { flex: 1; min-width: 0; }
.jr-row__col--time { font-size: 11px; color: var(--text-4); font-family: 'JetBrains Mono', monospace; flex-shrink: 0; }
.jr-row__col--status { flex-shrink: 0; display: flex; align-items: center; gap: 6px; }

.jr-row__title {
  font-size: 13px; font-weight: 500; color: var(--text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.jr-row__title code { font-family: inherit; font-weight: 500; }
.jr-row__chat { font-size: 11px; color: var(--text-4); margin-left: 6px; }
.jr-row__chat code { font-family: 'JetBrains Mono', monospace; }
.jr-row__sub {
  font-size: 12px; color: var(--text-3);
  margin-top: 2px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.jr-row__sub code { font-family: 'JetBrains Mono', monospace; font-size: 11px; }
.jr-row__attempts {
  font-family: 'JetBrains Mono', monospace; font-size: 10px; color: var(--text-4);
}
.jr-row__chev { width: 14px; height: 14px; color: var(--text-4); flex-shrink: 0; }
.jr-row__chev :deep(svg) { width: 14px; height: 14px; }

.jr-row__expand {
  background: var(--panel);
  border-top: 1px dashed var(--border);
  padding: 12px 16px 14px 60px;
  font-size: 12px;
}
.jr-row__exp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
  color: var(--text-2);
}
.jr-row__exp-grid > div { display: flex; flex-direction: column; gap: 2px; }
.jr-row__exp-grid > div > span { font-size: 10px; letter-spacing: .12em; text-transform: uppercase; color: var(--text-4); }
.jr-row__exp-grid > div > code { font-family: 'JetBrains Mono', monospace; color: var(--text); }

.jr-row__error {
  margin-top: 10px; padding: 8px 10px;
  background: #fbe8e7; border: 1px solid #f3c5c2; border-radius: 7px;
  color: #b3261e; font-size: 12px;
  display: flex; gap: 8px; align-items: flex-start;
}
.jr-row__error :deep(svg) { width: 14px; height: 14px; flex-shrink: 0; margin-top: 1px; }

.badge {
  display: inline-flex; align-items: center;
  font-size: 11px; font-weight: 500; padding: 3px 8px; border-radius: 5px;
}
.badge--status-active { background: var(--status-active-bg); color: var(--status-active-fg); }
.badge--status-former { background: var(--panel); color: var(--text-3); }
.badge--role          { background: var(--role-bg); color: var(--role-fg); }
.badge--neutral       { background: var(--panel); color: var(--text-2); }
.badge--status-error  { background: #fbe8e7; color: #b3261e; }

.jr__body::-webkit-scrollbar { width: 10px; }
.jr__body::-webkit-scrollbar-track { background: transparent; }
.jr__body::-webkit-scrollbar-thumb {
  background: var(--scrollbar, var(--border-strong));
  border-radius: 6px;
  border: 2px solid transparent;
  background-clip: padding-box;
}
</style>
