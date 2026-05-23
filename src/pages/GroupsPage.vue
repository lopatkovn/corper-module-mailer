<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { usePortal } from '../composables/usePortal'
import { api } from '../api'
import Card from '../components/Card.vue'
import Btn from '../components/Btn.vue'

const { canManage, branches } = usePortal()

interface Group {
  id: number
  chat_id: number
  title: string
  chat_type: string
  branch_id: number | null
  is_member: boolean
  can_send: boolean
  last_seen_at: string | null
  added_at: string
}

const groups = ref<Group[]>([])
const loading = ref(true)
const checkingId = ref<number | null>(null)
const addModal = ref(false)
const newGroup = ref({ chat_id: '', title: '', branch_id: null as number | null })
const adding = ref(false)
const addError = ref('')

async function loadGroups() {
  loading.value = true
  try {
    groups.value = await api.get('/api/mailer/groups').then(r => r.data)
  } finally { loading.value = false }
}

function branchName(bid: number | null | undefined): string {
  if (!bid) return ''
  return branches.value.find(b => b.id === bid)?.name || `#${bid}`
}

function statusOf(g: Group): 'ok' | 'cannot_send' | 'not_member' {
  if (!g.is_member) return 'not_member'
  if (!g.can_send) return 'cannot_send'
  return 'ok'
}

async function setBranch(g: Group, bid: number | null) {
  try {
    await api.put(`/api/mailer/groups/${g.id}`, { branch_id: bid })
    g.branch_id = bid
  } catch (e: any) {
    alert('Ошибка: ' + (e?.response?.data?.error || e.message))
  }
}

async function checkGroup(g: Group) {
  checkingId.value = g.id
  try {
    const res = await api.post(`/api/mailer/groups/${g.id}/check`).then(r => r.data)
    if (!res.ok) {
      alert('Не удалось проверить: ' + (res.error || 'неизвестно'))
    }
    await loadGroups()
  } finally { checkingId.value = null }
}

async function removeGroup(g: Group) {
  if (!confirm(`Удалить группу «${g.title || g.chat_id}»?`)) return
  await api.delete(`/api/mailer/groups/${g.id}`)
  await loadGroups()
}

function openAdd() {
  newGroup.value = { chat_id: '', title: '', branch_id: null }
  addError.value = ''
  addModal.value = true
}

async function submitAdd() {
  addError.value = ''
  if (!newGroup.value.chat_id || isNaN(Number(newGroup.value.chat_id))) {
    addError.value = 'chat_id обязателен и должен быть числом'
    return
  }
  adding.value = true
  try {
    await api.post('/api/mailer/groups', {
      chat_id: Number(newGroup.value.chat_id),
      title: newGroup.value.title,
      branch_id: newGroup.value.branch_id,
    })
    addModal.value = false
    await loadGroups()
  } catch (e: any) {
    addError.value = e?.response?.data?.error || e.message
  } finally { adding.value = false }
}

onMounted(loadGroups)
</script>

<template>
  <div class="gr">
    <header class="gr__head">
      <div>
        <h1 class="gr__title">Telegram-группы</h1>
        <p class="gr__hint">Добавьте бота в групповой чат — он появится здесь автоматически
          (после ≤30 секунд). Привяжите группу к филиалу, чтобы события маршрутизировались туда.</p>
      </div>
      <Btn variant="primary" icon="plus" @click="openAdd" :disabled="!canManage()">Добавить вручную</Btn>
    </header>

    <div v-if="loading" class="gr__empty">Загрузка…</div>
    <div v-else-if="!groups.length" class="gr__empty">
      Пока нет групп. <br />
      Добавьте бота в Telegram-чат (как администратора с правом писать) — он зарегистрирует
      чат сам. Либо нажмите «Добавить вручную» и впишите chat_id (взять у @getmyid_bot).
    </div>

    <div v-else class="gr__grid">
      <Card v-for="g in groups" :key="g.id" variant="surface">
        <template #action>
          <span :class="['mark', `mark--${statusOf(g)}`]">
            <span class="mark__dot"></span>
            {{ statusOf(g) === 'ok' ? 'Готов' : statusOf(g) === 'cannot_send' ? 'Без прав' : 'Не в чате' }}
          </span>
        </template>
        <div class="gr-row gr-row--top">
          <div class="gr-row__title">{{ g.title || '(без названия)' }}</div>
          <div class="gr-row__type">{{ g.chat_type }}</div>
        </div>
        <div class="gr-row gr-row--id">chat_id: <code>{{ g.chat_id }}</code></div>
        <div class="gr-row">
          <label class="gr-row__label">Филиал:</label>
          <select :value="g.branch_id ?? ''"
                  @change="setBranch(g, ($event.target as HTMLSelectElement).value ? Number(($event.target as HTMLSelectElement).value) : null)"
                  :disabled="!canManage()">
            <option value="">— не привязан —</option>
            <option v-for="b in branches" :key="b.id" :value="b.id">{{ b.name }}</option>
          </select>
        </div>
        <div v-if="g.last_seen_at" class="gr-row gr-row__meta">
          Последняя проверка: {{ new Date(g.last_seen_at).toLocaleString('ru-RU') }}
        </div>
        <div class="gr-row gr-row__actions">
          <Btn variant="ghost" icon="refresh-cw" :disabled="checkingId === g.id || !canManage()"
               @click="checkGroup(g)">
            {{ checkingId === g.id ? 'Проверяю…' : 'Проверить' }}
          </Btn>
          <Btn variant="ghost" icon="trash-2" danger
               @click="removeGroup(g)" :disabled="!canManage()">Удалить</Btn>
        </div>
      </Card>
    </div>

    <!-- Add modal -->
    <div v-if="addModal" class="modal-overlay" @click.self="addModal = false">
      <div class="modal">
        <h3 class="modal__title">Добавить группу вручную</h3>
        <div class="modal__fields">
          <label class="field">
            <span class="field__label">chat_id (число)</span>
            <input v-model="newGroup.chat_id" placeholder="-1001234567890" />
            <span class="field__hint">Получить можно через @getmyid_bot в нужном чате.</span>
          </label>
          <label class="field">
            <span class="field__label">Название (необязательно)</span>
            <input v-model="newGroup.title" placeholder="Отдел продаж" />
          </label>
          <label class="field">
            <span class="field__label">Филиал</span>
            <select v-model="newGroup.branch_id">
              <option :value="null">— не привязывать —</option>
              <option v-for="b in branches" :key="b.id" :value="b.id">{{ b.name }}</option>
            </select>
          </label>
        </div>
        <p v-if="addError" class="modal__err">{{ addError }}</p>
        <div class="modal__actions">
          <Btn variant="ghost" @click="addModal = false">Отмена</Btn>
          <Btn variant="primary" :disabled="adding" @click="submitAdd">
            {{ adding ? 'Добавляю…' : 'Добавить' }}
          </Btn>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.gr__head {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 16px; margin-bottom: 16px;
}
.gr__title { margin: 0 0 6px; font-size: 22px; font-weight: 600; color: var(--text); }
.gr__hint { margin: 0; max-width: 680px; color: var(--text-3); font-size: 13px; line-height: 1.5; }
.gr__empty {
  padding: 60px 20px; text-align: center;
  background: var(--panel); border: 1px dashed var(--border); border-radius: 12px;
  color: var(--text-3); line-height: 1.6;
}
.gr__grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); }
.gr-row { display: flex; gap: 10px; align-items: center; margin-bottom: 8px; font-size: 13px; color: var(--text); }
.gr-row--top { align-items: baseline; justify-content: space-between; gap: 8px; }
.gr-row__title { font-weight: 600; font-size: 14px; color: var(--text); }
.gr-row__type {
  font-family: 'JetBrains Mono', monospace; font-size: 11px;
  color: var(--text-4); text-transform: uppercase; letter-spacing: .04em;
}
.gr-row--id code { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-3); }
.gr-row__label { color: var(--text-3); font-size: 12px; flex-shrink: 0; }
.gr-row__meta { font-size: 11px; color: var(--text-4); }
.gr-row__actions { margin-top: 8px; gap: 8px; }
.gr-row select {
  padding: 5px 9px; font-size: 12px;
  border: 1px solid var(--border); border-radius: 7px;
  background: var(--bg); color: var(--text); font-family: inherit; flex: 1; min-width: 0;
}

.mark { display: inline-flex; align-items: center; gap: 6px;
        padding: 3px 9px; border-radius: 999px; font-size: 11px; font-weight: 500;
        border: 1px solid var(--border); background: var(--surface); }
.mark__dot { width: 6px; height: 6px; border-radius: 50%; background: var(--text-4); }
.mark--ok { color: #0a7d3e; border-color: #b6e3c2; background: #e7f6ec; }
.mark--ok .mark__dot { background: #1aae5b; }
.mark--cannot_send { color: #8a6d10; border-color: #f0e2a3; background: #fcf6dd; }
.mark--cannot_send .mark__dot { background: #d9a417; }
.mark--not_member { color: #b3261e; border-color: #f3c5c2; background: #fbe8e7; }
.mark--not_member .mark__dot { background: #d3372d; }

.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.35);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.modal {
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 20px; min-width: 380px; max-width: 460px;
  box-shadow: 0 10px 40px rgba(0,0,0,.16);
}
.modal__title { margin: 0 0 14px; font-size: 16px; font-weight: 600; }
.modal__fields { display: flex; flex-direction: column; gap: 12px; }
.field { display: flex; flex-direction: column; gap: 4px; }
.field__label { font-size: 11px; color: var(--text-3); font-weight: 500; }
.field__hint { font-size: 11px; color: var(--text-4); }
.field input, .field select {
  padding: 8px 11px; font-size: 13px;
  border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg); color: var(--text); font-family: inherit;
}
.modal__err { margin: 12px 0 0; padding: 8px 12px;
              background: #fbe8e7; border: 1px solid #f3c5c2; border-radius: 8px;
              color: #b3261e; font-size: 12px; }
.modal__actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 14px; }
</style>
