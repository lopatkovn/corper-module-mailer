<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { usePortal } from '../composables/usePortal'
import { api } from '../api'
import Card from '../components/Card.vue'
import Btn from '../components/Btn.vue'

const { canManage, branches, employees } = usePortal()

interface EventType { id: number; key: string; label: string; source_module: string }
interface ChannelPub { kind: string; is_enabled: boolean; label: string; status: string }
interface Recipients {
  emails?: string[]; employee_ids?: number[];
  branch_ids?: number[]; telegram_group_ids?: number[];
}
interface Rule {
  id: number; event_type_id: number; channel_id: number;
  recipients: Recipients; is_enabled: boolean; priority: number
}
interface Group { id: number; chat_id: number; title: string; branch_id: number | null }

const rules = ref<Rule[]>([])
const eventTypes = ref<EventType[]>([])
const channels = ref<Array<{ id: number; kind: string; label: string }>>([])
const groups = ref<Group[]>([])
const loading = ref(true)

const editorOpen = ref(false)
const editing = ref<Rule | null>(null)
const isNew = ref(false)
const saving = ref(false)
const error = ref('')

async function loadAll() {
  loading.value = true
  try {
    const [rs, ets, cps, gs, ce, ct] = await Promise.all([
      api.get('/api/mailer/rules').then(r => r.data),
      api.get('/api/mailer/event-types').then(r => r.data),
      api.get('/api/mailer/channels').then(r => r.data),
      api.get('/api/mailer/groups').then(r => r.data),
      api.get('/api/mailer/channels/email').then(r => r.data),
      api.get('/api/mailer/channels/telegram').then(r => r.data),
    ])
    rules.value = rs
    eventTypes.value = ets
    groups.value = gs
    // полные channel-объекты (id+kind+label) собираем из admin GET
    const list: Array<{ id: number; kind: string; label: string }> = []
    if (ce.id) list.push({ id: ce.id, kind: ce.kind, label: ce.label || 'Email' })
    if (ct.id) list.push({ id: ct.id, kind: ct.kind, label: ct.label || 'Telegram' })
    channels.value = list
  } finally { loading.value = false }
}

function eventTypeLabel(id: number) {
  return eventTypes.value.find(e => e.id === id)?.label || `#${id}`
}
function eventTypeKey(id: number) {
  return eventTypes.value.find(e => e.id === id)?.key || ''
}
function channelLabel(id: number) {
  const c = channels.value.find(c => c.id === id)
  return c ? `${c.kind === 'email' ? '✉' : '✈'} ${c.label || c.kind}` : `#${id}`
}
function summarizeRecipients(r: Recipients): string {
  const parts: string[] = []
  if (r.emails?.length) parts.push(`${r.emails.length} email`)
  if (r.employee_ids?.length) parts.push(`${r.employee_ids.length} сотр`)
  if (r.branch_ids?.length) parts.push(`${r.branch_ids.length} фил`)
  if (r.telegram_group_ids?.length) parts.push(`${r.telegram_group_ids.length} ТГ`)
  return parts.join(' · ') || 'нет получателей'
}

function openNew() {
  isNew.value = true
  editing.value = {
    id: 0,
    event_type_id: eventTypes.value[0]?.id || 0,
    channel_id: channels.value[0]?.id || 0,
    recipients: { emails: [], employee_ids: [], branch_ids: [], telegram_group_ids: [] },
    is_enabled: true,
    priority: 100,
  }
  error.value = ''
  editorOpen.value = true
}

function openEdit(r: Rule) {
  isNew.value = false
  editing.value = JSON.parse(JSON.stringify({
    ...r,
    recipients: {
      emails: r.recipients.emails ?? [],
      employee_ids: r.recipients.employee_ids ?? [],
      branch_ids: r.recipients.branch_ids ?? [],
      telegram_group_ids: r.recipients.telegram_group_ids ?? [],
    },
  }))
  error.value = ''
  editorOpen.value = true
}

async function save() {
  if (!editing.value) return
  if (!editing.value.event_type_id || !editing.value.channel_id) {
    error.value = 'Выберите событие и канал'
    return
  }
  saving.value = true
  error.value = ''
  try {
    if (isNew.value) {
      await api.post('/api/mailer/rules', editing.value)
    } else {
      await api.put(`/api/mailer/rules/${editing.value.id}`, editing.value)
    }
    editorOpen.value = false
    await loadAll()
  } catch (e: any) {
    error.value = e?.response?.data?.error || e.message
  } finally { saving.value = false }
}

async function toggleEnabled(r: Rule) {
  await api.put(`/api/mailer/rules/${r.id}`, { is_enabled: !r.is_enabled })
  await loadAll()
}

async function remove(r: Rule) {
  if (!confirm('Удалить правило?')) return
  await api.delete(`/api/mailer/rules/${r.id}`)
  await loadAll()
}

// Recipients editor helpers
const newEmail = ref('')
function addEmail() {
  if (!editing.value || !newEmail.value.includes('@')) return
  editing.value.recipients.emails = [...(editing.value.recipients.emails || []), newEmail.value.trim()]
  newEmail.value = ''
}
function removeEmail(i: number) {
  if (!editing.value) return
  editing.value.recipients.emails!.splice(i, 1)
}
function toggleEmployee(eid: number) {
  if (!editing.value) return
  const arr = editing.value.recipients.employee_ids = editing.value.recipients.employee_ids || []
  const i = arr.indexOf(eid)
  if (i >= 0) arr.splice(i, 1); else arr.push(eid)
}
function toggleBranch(bid: number) {
  if (!editing.value) return
  const arr = editing.value.recipients.branch_ids = editing.value.recipients.branch_ids || []
  const i = arr.indexOf(bid)
  if (i >= 0) arr.splice(i, 1); else arr.push(bid)
}
function toggleGroup(gid: number) {
  if (!editing.value) return
  const arr = editing.value.recipients.telegram_group_ids = editing.value.recipients.telegram_group_ids || []
  const i = arr.indexOf(gid)
  if (i >= 0) arr.splice(i, 1); else arr.push(gid)
}

const selectedChannelKind = computed(() => {
  if (!editing.value) return ''
  return channels.value.find(c => c.id === editing.value!.channel_id)?.kind || ''
})

onMounted(loadAll)
</script>

<template>
  <div class="ru">
    <header class="ru__head">
      <div>
        <h1 class="ru__title">Правила маршрутизации</h1>
        <p class="ru__hint">Событие → канал → получатели. События появляются в каталоге
          автоматически при деплое модулей-источников.</p>
      </div>
      <Btn variant="primary" icon="plus" :disabled="!canManage() || !eventTypes.length || !channels.length"
           @click="openNew">Добавить правило</Btn>
    </header>

    <div v-if="loading" class="ru__empty">Загрузка…</div>
    <div v-else-if="!eventTypes.length" class="ru__empty">
      Каталог событий пуст. Он наполняется автоматически при деплое модулей с
      <code>emits</code> в <code>module.json</code>.
    </div>
    <div v-else-if="!channels.length" class="ru__empty">
      Сначала настройте хотя бы один канал на вкладке «Каналы».
    </div>
    <div v-else-if="!rules.length" class="ru__empty">
      Правил ещё нет. Нажмите «Добавить правило».
    </div>

    <table v-else class="ru__table">
      <thead>
        <tr>
          <th>Событие</th>
          <th>Канал</th>
          <th>Получатели</th>
          <th class="num">Приоритет</th>
          <th>Вкл.</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in rules" :key="r.id" :class="{ 'tr--off': !r.is_enabled }">
          <td>
            <div class="ev__label">{{ eventTypeLabel(r.event_type_id) }}</div>
            <code class="ev__key">{{ eventTypeKey(r.event_type_id) }}</code>
          </td>
          <td>{{ channelLabel(r.channel_id) }}</td>
          <td><span class="recip">{{ summarizeRecipients(r.recipients) }}</span></td>
          <td class="num">{{ r.priority }}</td>
          <td>
            <label class="switch">
              <input type="checkbox" :checked="r.is_enabled" :disabled="!canManage()"
                     @change="toggleEnabled(r)" />
              <span></span>
            </label>
          </td>
          <td class="actions">
            <button class="link" :disabled="!canManage()" @click="openEdit(r)">Изменить</button>
            <button class="link link--danger" :disabled="!canManage()" @click="remove(r)">Удалить</button>
          </td>
        </tr>
      </tbody>
    </table>

    <!-- Editor modal -->
    <div v-if="editorOpen" class="modal-overlay" @click.self="editorOpen = false">
      <div class="modal modal--lg">
        <h3 class="modal__title">{{ isNew ? 'Новое правило' : 'Правило' }}</h3>
        <div v-if="editing" class="modal__fields">
          <label class="field">
            <span class="field__label">Событие</span>
            <select v-model="editing.event_type_id">
              <option v-for="e in eventTypes" :key="e.id" :value="e.id">
                {{ e.label }} ({{ e.key }})
              </option>
            </select>
          </label>

          <label class="field">
            <span class="field__label">Канал</span>
            <select v-model="editing.channel_id">
              <option v-for="c in channels" :key="c.id" :value="c.id">
                {{ c.kind === 'email' ? '✉ Email' : '✈ Telegram' }} — {{ c.label || c.kind }}
              </option>
            </select>
          </label>

          <fieldset class="group">
            <legend>Получатели</legend>

            <div v-if="selectedChannelKind === 'email'">
              <div class="sub">Прямые email-адреса:</div>
              <div class="chips">
                <span class="chip" v-for="(e, i) in editing.recipients.emails" :key="i">
                  {{ e }} <button type="button" @click="removeEmail(i)">×</button>
                </span>
                <div class="chip-add">
                  <input v-model="newEmail" placeholder="email@example.com" @keyup.enter="addEmail" />
                  <Btn variant="ghost" @click="addEmail">Добавить</Btn>
                </div>
              </div>
            </div>

            <div v-if="selectedChannelKind === 'email'">
              <div class="sub">Сотрудники (адресуем по их email):</div>
              <div class="picker">
                <label v-for="e in employees" :key="e.id" class="picker__item">
                  <input type="checkbox" :checked="editing.recipients.employee_ids?.includes(e.id)"
                         @change="toggleEmployee(e.id)" />
                  <span>{{ e.name }} <small>{{ e.email || '—' }}</small></span>
                </label>
                <div v-if="!employees.length" class="picker__empty">Нет сотрудников</div>
              </div>
            </div>

            <div v-if="selectedChannelKind === 'email'">
              <div class="sub">Филиалы (все сотрудники филиала):</div>
              <div class="chip-row">
                <label v-for="b in branches" :key="b.id" class="chip-toggle">
                  <input type="checkbox" :checked="editing.recipients.branch_ids?.includes(b.id)"
                         @change="toggleBranch(b.id)" />
                  <span>{{ b.name }}</span>
                </label>
              </div>
            </div>

            <div v-if="selectedChannelKind === 'telegram'">
              <div class="sub">Telegram-группы:</div>
              <div class="chip-row">
                <label v-for="g in groups" :key="g.id" class="chip-toggle">
                  <input type="checkbox" :checked="editing.recipients.telegram_group_ids?.includes(g.id)"
                         @change="toggleGroup(g.id)" />
                  <span>{{ g.title || `chat_id=${g.chat_id}` }}</span>
                </label>
                <div v-if="!groups.length" class="picker__empty">Нет групп. Добавьте на вкладке «Группы».</div>
              </div>
            </div>
          </fieldset>

          <div class="row row--2">
            <label class="field field--narrow">
              <span class="field__label">Приоритет</span>
              <input v-model.number="editing.priority" type="number" />
            </label>
            <label class="check">
              <input type="checkbox" v-model="editing.is_enabled" />
              <span>Включено</span>
            </label>
          </div>
        </div>

        <p v-if="error" class="modal__err">{{ error }}</p>
        <div class="modal__actions">
          <Btn variant="ghost" @click="editorOpen = false">Отмена</Btn>
          <Btn variant="primary" :disabled="saving" @click="save">
            {{ saving ? 'Сохраняю…' : 'Сохранить' }}
          </Btn>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ru__head {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 16px; margin-bottom: 16px;
}
.ru__title { margin: 0 0 6px; font-size: 22px; font-weight: 600; color: var(--text); }
.ru__hint { margin: 0; max-width: 680px; color: var(--text-3); font-size: 13px; line-height: 1.5; }
.ru__empty {
  padding: 60px 20px; text-align: center;
  background: var(--panel); border: 1px dashed var(--border); border-radius: 12px;
  color: var(--text-3); line-height: 1.6;
}
.ru__table {
  width: 100%; border-collapse: collapse; background: var(--surface);
  border: 1px solid var(--border); border-radius: 12px; overflow: hidden;
  font-size: 13px;
}
.ru__table th, .ru__table td { padding: 11px 14px; text-align: left; vertical-align: middle; border-bottom: 1px solid var(--border); }
.ru__table th { background: var(--panel); font-weight: 500; font-size: 11px; color: var(--text-3);
                text-transform: uppercase; letter-spacing: .04em; }
.ru__table tbody tr:last-child td { border-bottom: 0; }
.ru__table .num { text-align: right; }
.tr--off td { opacity: .55; }
.ev__label { color: var(--text); }
.ev__key { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-4); }
.recip { color: var(--text-3); font-size: 12px; }
.actions { white-space: nowrap; }
.link { background: 0; border: 0; padding: 4px 8px; cursor: pointer;
        color: var(--accent); font-size: 12px; font-family: inherit; }
.link--danger { color: var(--danger); }
.link:disabled { opacity: .4; cursor: not-allowed; }

.switch { position: relative; display: inline-block; width: 32px; height: 18px; }
.switch input { opacity: 0; width: 0; height: 0; }
.switch span { position: absolute; inset: 0; background: var(--border);
               border-radius: 999px; transition: .15s; cursor: pointer; }
.switch span::before { content: ''; position: absolute; left: 2px; top: 2px;
                      width: 14px; height: 14px; background: white;
                      border-radius: 50%; transition: .15s; }
.switch input:checked + span { background: var(--accent); }
.switch input:checked + span::before { transform: translateX(14px); }

.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.35);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.modal {
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 22px; min-width: 460px; box-shadow: 0 10px 40px rgba(0,0,0,.16);
}
.modal--lg { min-width: 560px; max-width: 720px; max-height: 86vh; overflow-y: auto; }
.modal__title { margin: 0 0 16px; font-size: 17px; font-weight: 600; }
.modal__fields { display: flex; flex-direction: column; gap: 14px; }
.field { display: flex; flex-direction: column; gap: 4px; }
.field--narrow { max-width: 140px; }
.field__label { font-size: 11px; color: var(--text-3); font-weight: 500; }
.field input, .field select {
  padding: 8px 11px; font-size: 13px;
  border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg); color: var(--text); font-family: inherit;
}
.row { display: flex; gap: 12px; align-items: flex-end; }
.check { display: flex; align-items: center; gap: 8px; font-size: 13px; padding-bottom: 8px; }
.check input { width: 16px; height: 16px; accent-color: var(--accent); }
.group { border: 1px solid var(--border); border-radius: 9px; padding: 12px 14px; margin: 0; }
.group > legend { padding: 0 6px; font-size: 10px; letter-spacing: .14em;
                  text-transform: uppercase; color: var(--text-4); font-weight: 500; }
.sub { font-size: 12px; color: var(--text-3); margin-top: 10px; margin-bottom: 6px; font-weight: 500; }
.sub:first-of-type { margin-top: 0; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.chip { display: inline-flex; align-items: center; gap: 4px;
        padding: 4px 10px; border-radius: 999px; font-size: 12px;
        background: var(--panel); border: 1px solid var(--border); color: var(--text); }
.chip button { background: 0; border: 0; color: var(--text-3); cursor: pointer; font-size: 14px; padding: 0 2px; }
.chip-add { display: flex; gap: 6px; align-items: center; }
.chip-add input { padding: 6px 10px; font-size: 12px;
                  border: 1px solid var(--border); border-radius: 7px;
                  background: var(--bg); color: var(--text); font-family: inherit; }
.picker { max-height: 200px; overflow-y: auto; background: var(--bg);
          border: 1px solid var(--border); border-radius: 8px; padding: 8px; }
.picker__item { display: flex; align-items: center; gap: 8px; padding: 4px 6px;
                font-size: 13px; cursor: pointer; border-radius: 5px; }
.picker__item:hover { background: var(--panel); }
.picker__item small { color: var(--text-4); margin-left: 6px; font-size: 11px; }
.picker__empty { padding: 12px; text-align: center; color: var(--text-4); font-size: 12px; }
.chip-row { display: flex; flex-wrap: wrap; gap: 6px; }
.chip-toggle { display: inline-flex; align-items: center; gap: 6px;
               padding: 5px 10px; border-radius: 999px; font-size: 12px;
               border: 1px solid var(--border); background: var(--bg);
               cursor: pointer; user-select: none; }
.chip-toggle input { accent-color: var(--accent); }
.chip-toggle:has(input:checked) { background: var(--panel); border-color: var(--accent); }
.modal__err { margin: 12px 0 0; padding: 8px 12px;
              background: #fbe8e7; border: 1px solid #f3c5c2; border-radius: 8px;
              color: #b3261e; font-size: 12px; }
.modal__actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 16px; }
</style>
