<script setup lang="ts">
import { ref, computed, onMounted, onUpdated, nextTick, watch } from 'vue'
import { usePortal } from '../composables/usePortal'
import { api } from '../api'
import PageHeader from '../components/PageHeader.vue'
import PrimaryBtn from '../components/PrimaryBtn.vue'
import GhostBtn from '../components/GhostBtn.vue'
import GroupDetailPanel from './GroupDetailPanel.vue'

declare const feather: any

defineProps<{ tabs: any[]; activeTab: string }>()
const emit = defineEmits<{
  (e: 'switch-tab', id: string): void
  (e: 'count', n: number): void
}>()

const { canManage, branches } = usePortal()

interface Group {
  id: number; chat_id: number; title: string; chat_type: string;
  branch_id: number | null
  is_member: boolean; can_send: boolean
  last_seen_at: string | null; added_at: string
}

const groups = ref<Group[]>([])
const loading = ref(true)
const search = ref('')
const selectedId = ref<number | null>(null)
const addModal = ref(false)
const newG = ref({ chat_id: '', title: '', branch_id: null as number | null })
const addError = ref('')
const adding = ref(false)

async function load() {
  loading.value = true
  try {
    groups.value = await api.get('/api/mailer/groups').then(r => r.data)
    emit('count', groups.value.length)
  } finally {
    loading.value = false
    nextTick(() => feather?.replace())
  }
}

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return groups.value
  return groups.value.filter(g => {
    const blob = `${g.title} ${g.chat_id} ${branchName(g.branch_id)}`.toLowerCase()
    return blob.includes(q)
  })
})

function branchName(bid: number | null): string {
  if (!bid) return ''
  return branches.value.find(b => b.id === bid)?.name || `#${bid}`
}
function statusOf(g: Group): { variant: string; label: string } {
  if (!g.is_member) return { variant: 'status-error', label: 'не в чате' }
  if (!g.can_send)  return { variant: 'role',          label: 'без прав' }
  return { variant: 'status-active', label: 'готов' }
}
const _PALETTE = ['#E8A66B', '#C9A2D7', '#94B8D9', '#A8C9A3', '#7FB8B0', '#4DBFA6', '#7B6FE0']
function dotFor(name: string): string {
  let h = 0; for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  return _PALETTE[h % _PALETTE.length]
}
function fmtTime(d: string | null): string {
  if (!d) return ''
  const date = new Date(d), now = new Date()
  const same = date.toDateString() === now.toDateString()
  return same ? date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
              : date.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' })
}

function selectGroup(id: number | null) { selectedId.value = id }
const selectedGroup = computed(() => groups.value.find(g => g.id === selectedId.value) || null)

function openAdd() {
  newG.value = { chat_id: '', title: '', branch_id: null }
  addError.value = ''
  addModal.value = true
}
async function submitAdd() {
  if (!newG.value.chat_id || isNaN(Number(newG.value.chat_id))) {
    addError.value = 'chat_id обязателен и должен быть числом'
    return
  }
  adding.value = true; addError.value = ''
  try {
    const r = await api.post('/api/mailer/groups', {
      chat_id: Number(newG.value.chat_id),
      title: newG.value.title,
      branch_id: newG.value.branch_id,
    }).then(r => r.data)
    addModal.value = false
    await load()
    selectGroup(r.id)
  } catch (e: any) {
    addError.value = e?.response?.data?.error || e.message
  } finally { adding.value = false }
}

onMounted(load)
onUpdated(() => nextTick(() => feather?.replace()))
</script>

<template>
  <div class="page">
    <div class="page__main">
      <PageHeader
        title="Служба рассылок"
        :count="loading ? '' : `${filtered.length} из ${groups.length}`"
        :tabs="tabs"
        :active-tab="activeTab"
        :search="search"
        search-placeholder="Поиск по названию, chat_id, филиалу"
        @tab="(id: string) => emit('switch-tab', id)"
        @update:search="(v: string) => search = v"
      >
        <template #primary>
          <PrimaryBtn :disabled="!canManage()" @click="openAdd">Добавить группу</PrimaryBtn>
        </template>
      </PageHeader>

      <div v-if="loading" class="page__empty">Загрузка…</div>
      <div v-else-if="!groups.length" class="page__empty">
        <div class="page__empty-title">Нет Telegram-групп</div>
        <div class="page__empty-hint">
          Добавьте бота (см. вкладку «Каналы») и пригласите его в групповой чат —
          группа появится здесь автоматически.<br />
          Либо нажмите <strong>«Добавить группу»</strong> вверху и впишите chat_id вручную
          (узнать у <code>@getmyid_bot</code>).
        </div>
      </div>
      <div v-else-if="!filtered.length" class="page__empty">Ничего не найдено</div>

      <div v-else class="page__grid">
        <button
          v-for="g in filtered" :key="g.id"
          :class="['gr-card', { 'gr-card--selected': g.id === selectedId }]"
          @click="selectGroup(g.id)"
        >
          <div class="gr-card__head">
            <span class="gr-card__dot-wrap" :style="{ background: dotFor(g.title || String(g.chat_id)) + '25' }">
              <span class="gr-card__dot" :style="{ background: dotFor(g.title || String(g.chat_id)) }"></span>
            </span>
            <div class="gr-card__roles">
              <span class="gr-card__role" title="Telegram"><i data-feather="send"></i></span>
              <span v-if="g.chat_type === 'channel'" class="gr-card__role" title="Канал">
                <i data-feather="radio"></i>
              </span>
            </div>
            <span :class="['badge', `badge--${statusOf(g).variant}`]">
              {{ statusOf(g).label }}
            </span>
          </div>

          <div class="gr-card__name">{{ g.title || '(без названия)' }}</div>

          <div class="gr-card__meta">
            <div class="gr-card__meta-row">
              <i data-feather="hash"></i>
              <span class="gr-card__mono">{{ g.chat_id }}</span>
            </div>
            <div v-if="g.branch_id" class="gr-card__meta-row">
              <i data-feather="map-pin"></i>
              <span>{{ branchName(g.branch_id) }}</span>
            </div>
            <div v-else class="gr-card__meta-row gr-card__meta-row--empty">
              <i data-feather="map-pin"></i>
              <span>филиал не привязан</span>
            </div>
          </div>

          <div class="gr-card__footer">
            <span>{{ g.last_seen_at ? 'Проверен ' + fmtTime(g.last_seen_at) : 'Не проверялся' }}</span>
            <i data-feather="chevron-right"></i>
          </div>
        </button>
      </div>
    </div>

    <GroupDetailPanel
      v-if="selectedGroup"
      :group="selectedGroup"
      :can-manage="canManage()"
      @close="selectGroup(null)"
      @updated="load"
      @deleted="async () => { selectGroup(null); await load() }"
    />

    <!-- Add modal -->
    <div v-if="addModal" class="modal-bg" @click.self="addModal = false">
      <div class="modal">
        <h3 class="modal__title">Добавить группу вручную</h3>
        <div class="modal__fields">
          <div class="drawer-field">
            <label class="drawer-field__label">chat_id (число)</label>
            <input class="drawer-field__input drawer-field__input--mono"
                   v-model="newG.chat_id" placeholder="-1001234567890" />
            <div class="drawer-field__hint">Узнать через @getmyid_bot в нужном чате.</div>
          </div>
          <div class="drawer-field">
            <label class="drawer-field__label">Название (опционально)</label>
            <input class="drawer-field__input" v-model="newG.title" placeholder="Отдел продаж" />
          </div>
          <div class="drawer-field">
            <label class="drawer-field__label">Филиал</label>
            <select class="drawer-field__input" v-model="newG.branch_id">
              <option :value="null">— не привязывать —</option>
              <option v-for="b in branches" :key="b.id" :value="b.id">{{ b.name }}</option>
            </select>
          </div>
        </div>
        <p v-if="addError" class="modal__err">{{ addError }}</p>
        <div class="modal__actions">
          <GhostBtn @click="addModal = false">Отмена</GhostBtn>
          <PrimaryBtn :disabled="adding" @click="submitAdd">
            {{ adding ? 'Добавляю…' : 'Добавить' }}
          </PrimaryBtn>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { display: flex; height: 100%; min-height: 100vh; background: var(--bg); }
.page__main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; }
.page__empty {
  color: var(--text-4); text-align: center; padding: 60px 32px; font-size: 13px;
}
.page__empty-title { font-size: 14px; color: var(--text-2); margin-bottom: 6px; }
.page__empty-hint { font-size: 13px; color: var(--text-3); line-height: 1.6; max-width: 480px; margin: 0 auto; }
.page__empty-hint code { font-family: 'JetBrains Mono', monospace; color: var(--text); background: var(--panel); padding: 1px 6px; border-radius: 4px; }
.page__empty-hint strong { color: var(--text); }

.page__grid {
  flex: 1; overflow: auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
  padding: 18px 32px 32px;
}

.gr-card {
  background: var(--surface);
  border: 1px solid var(--border-2);
  border-radius: 12px;
  padding: 14px 14px 12px;
  cursor: pointer; text-align: left;
  display: flex; flex-direction: column; gap: 10px;
  font-family: inherit;
  transition: border-color .12s, box-shadow .12s;
}
.gr-card:hover { border-color: var(--border-strong); }
.gr-card--selected { border-color: var(--accent); box-shadow: 0 0 0 3px var(--ring); }

.gr-card__head { display: flex; justify-content: space-between; align-items: center; }
.gr-card__dot-wrap {
  width: 18px; height: 18px; border-radius: 5px;
  display: flex; align-items: center; justify-content: center;
}
.gr-card__dot { width: 6px; height: 6px; border-radius: 50%; }
.gr-card__roles { display: flex; align-items: center; gap: 4px; margin-right: auto; margin-left: 8px; }
.gr-card__role {
  width: 18px; height: 18px; border-radius: 5px;
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--panel); color: var(--text-3);
}
.gr-card__role :deep(svg) { width: 11px; height: 11px; }

.gr-card__name {
  font-size: 15px; font-weight: 600; letter-spacing: -0.01em;
  color: var(--text); word-break: break-word;
}

.gr-card__meta { display: flex; flex-direction: column; gap: 5px; }
.gr-card__meta-row {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--text-2); line-height: 1.4;
  overflow: hidden;
}
.gr-card__meta-row :deep(svg) { width: 12px; height: 12px; flex-shrink: 0; color: var(--text-4); }
.gr-card__meta-row span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gr-card__meta-row--empty { color: var(--placeholder); }
.gr-card__mono { font-family: 'JetBrains Mono', monospace; font-size: 11px; }

.gr-card__footer {
  padding-top: 8px; border-top: 1px dashed var(--border-2);
  font-size: 11px; color: var(--text-4);
  display: flex; justify-content: space-between; align-items: center;
}
.gr-card__footer :deep(svg) { width: 12px; height: 12px; }

/* Badges */
.badge {
  display: inline-flex; align-items: center;
  font-size: 11px; font-weight: 500; padding: 3px 8px; border-radius: 5px; white-space: nowrap;
}
.badge--status-active { background: var(--status-active-bg); color: var(--status-active-fg); }
.badge--role          { background: var(--role-bg); color: var(--role-fg); }
.badge--neutral       { background: var(--panel); color: var(--text-2); }
.badge--status-error  { background: #fbe8e7; color: #b3261e; }

/* Modal */
.modal-bg {
  position: fixed; inset: 0; background: rgba(0,0,0,.35);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.modal {
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 22px; min-width: 380px; max-width: 460px;
  box-shadow: 0 10px 40px rgba(0,0,0,.16);
}
.modal__title { margin: 0 0 14px; font-size: 16px; font-weight: 600; color: var(--text); }
.modal__fields { display: flex; flex-direction: column; gap: 12px; }
.modal__err {
  margin: 12px 0 0; padding: 8px 12px;
  background: #fbe8e7; border: 1px solid #f3c5c2; border-radius: 8px;
  color: #b3261e; font-size: 12px;
}
.modal__actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 14px; }

.drawer-field { display: flex; flex-direction: column; gap: 6px; }
.drawer-field__label {
  font-size: 10px; font-weight: 500;
  letter-spacing: .16em; text-transform: uppercase;
  color: var(--text-4); font-family: 'JetBrains Mono', monospace;
}
.drawer-field__input {
  padding: 9px 12px; font-size: 13px;
  border: 1px solid var(--border-strong); border-radius: 8px;
  background: var(--surface); color: var(--text);
  font-family: inherit; outline: none;
}
.drawer-field__input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--ring); }
.drawer-field__input--mono { font-family: 'JetBrains Mono', monospace; }
.drawer-field__hint { font-size: 11px; color: var(--text-4); }
</style>
