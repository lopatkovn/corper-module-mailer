<script setup lang="ts">
import { ref, computed, watch, onMounted, onUpdated, nextTick } from 'vue'
import { usePortal } from '../composables/usePortal'
import { api } from '../api'
import DrawerSection from '../components/DrawerSection.vue'
import GhostBtn from '../components/GhostBtn.vue'

declare const feather: any

interface EventType { id: number; key: string; label: string; source_module: string }
interface ChannelMini { id: number; kind: string; label: string }
interface Group { id: number; chat_id: number; title: string }
interface Rule {
  id: number; event_type_id: number; channel_id: number;
  recipients: any; is_enabled: boolean; priority: number
}

const props = defineProps<{
  rule: Rule | null
  isNew: boolean
  eventTypes: EventType[]
  channels: ChannelMini[]
  groups: Group[]
  canManage: boolean
}>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved', rule: Rule): void
  (e: 'deleted'): void
}>()

const { branches, employees } = usePortal()

// Draft
const draft = ref<Rule>({
  id: 0, event_type_id: 0, channel_id: 0,
  recipients: { emails: [], employee_ids: [], branch_ids: [], telegram_group_ids: [] },
  is_enabled: true, priority: 100,
})
const editing = ref(false)
const saving = ref(false)
const error = ref('')
const newEmail = ref('')
const confirmDelete = ref(false)

watch(() => [props.rule, props.isNew], () => {
  if (props.isNew) {
    draft.value = {
      id: 0,
      event_type_id: props.eventTypes[0]?.id || 0,
      channel_id: props.channels[0]?.id || 0,
      recipients: { emails: [], employee_ids: [], branch_ids: [], telegram_group_ids: [] },
      is_enabled: true, priority: 100,
    }
    editing.value = true
  } else if (props.rule) {
    draft.value = {
      ...props.rule,
      recipients: {
        emails: props.rule.recipients?.emails ?? [],
        employee_ids: props.rule.recipients?.employee_ids ?? [],
        branch_ids: props.rule.recipients?.branch_ids ?? [],
        telegram_group_ids: props.rule.recipients?.telegram_group_ids ?? [],
      },
    }
    editing.value = false
  }
  error.value = ''
  newEmail.value = ''
  confirmDelete.value = false
}, { immediate: true, deep: true })

onMounted(() => nextTick(() => feather?.replace()))
onUpdated(() => nextTick(() => feather?.replace()))

const eventTypeLabel = computed(() => props.eventTypes.find(e => e.id === draft.value.event_type_id)?.label || '')
const eventTypeKey = computed(() => props.eventTypes.find(e => e.id === draft.value.event_type_id)?.key || '')
const eventTypeSource = computed(() => props.eventTypes.find(e => e.id === draft.value.event_type_id)?.source_module || '')
const selectedChannel = computed(() => props.channels.find(c => c.id === draft.value.channel_id))
const channelKind = computed(() => selectedChannel.value?.kind || '')

function startEdit() {
  if (!props.canManage) return
  editing.value = true
  error.value = ''
}
function cancelEdit() {
  if (props.isNew) {
    emit('close')
    return
  }
  if (props.rule) {
    draft.value = {
      ...props.rule,
      recipients: {
        emails: props.rule.recipients?.emails ?? [],
        employee_ids: props.rule.recipients?.employee_ids ?? [],
        branch_ids: props.rule.recipients?.branch_ids ?? [],
        telegram_group_ids: props.rule.recipients?.telegram_group_ids ?? [],
      },
    }
  }
  editing.value = false
  error.value = ''
}

async function save() {
  if (!draft.value.event_type_id || !draft.value.channel_id) {
    error.value = 'Выберите событие и канал'
    return
  }
  saving.value = true
  error.value = ''
  try {
    let result: Rule
    if (props.isNew) {
      result = await api.post('/api/mailer/rules', draft.value).then(r => r.data)
    } else {
      result = await api.put(`/api/mailer/rules/${draft.value.id}`, draft.value).then(r => r.data)
    }
    emit('saved', result)
  } catch (e: any) {
    error.value = e?.response?.data?.error || e.message
  } finally { saving.value = false }
}

async function remove() {
  if (!props.rule) return
  if (!confirmDelete.value) { confirmDelete.value = true; return }
  saving.value = true
  try {
    await api.delete(`/api/mailer/rules/${props.rule.id}`)
    emit('deleted')
  } finally { saving.value = false }
}

async function toggleEnabled() {
  if (!props.rule) return
  const next = !draft.value.is_enabled
  draft.value.is_enabled = next
  try {
    await api.put(`/api/mailer/rules/${props.rule.id}`, { is_enabled: next })
    emit('saved', { ...props.rule, is_enabled: next })
  } catch (e: any) {
    draft.value.is_enabled = !next
    error.value = e?.response?.data?.error || e.message
  }
}

// Recipients editors
function addEmail() {
  if (!newEmail.value.includes('@')) return
  draft.value.recipients.emails = [...(draft.value.recipients.emails || []), newEmail.value.trim()]
  newEmail.value = ''
}
function removeEmail(i: number) {
  draft.value.recipients.emails!.splice(i, 1)
}
function toggleEmployee(id: number) {
  const arr = draft.value.recipients.employee_ids = draft.value.recipients.employee_ids || []
  const i = arr.indexOf(id); i >= 0 ? arr.splice(i, 1) : arr.push(id)
}
function toggleBranch(id: number) {
  const arr = draft.value.recipients.branch_ids = draft.value.recipients.branch_ids || []
  const i = arr.indexOf(id); i >= 0 ? arr.splice(i, 1) : arr.push(id)
}
function toggleGroup(id: number) {
  const arr = draft.value.recipients.telegram_group_ids = draft.value.recipients.telegram_group_ids || []
  const i = arr.indexOf(id); i >= 0 ? arr.splice(i, 1) : arr.push(id)
}

function fmt(arr: any[] | undefined, fn: (x: any) => string): string {
  if (!arr || !arr.length) return ''
  return arr.map(fn).join(', ')
}
function employeeName(id: number): string {
  return employees.value.find(e => e.id === id)?.name || `#${id}`
}
function branchName(id: number): string {
  return branches.value.find(b => b.id === id)?.name || `#${id}`
}
function groupTitle(id: number): string {
  return props.groups.find(g => g.id === id)?.title || `#${id}`
}
</script>

<template>
  <aside class="dp">
    <div class="dp__header">
      <div class="dp__header-top">
        <span class="dp__eyebrow">RULE</span>
        <div class="dp__header-actions">
          <button v-if="!isNew && canManage && !editing" class="dp__icon-btn" title="Редактировать" @click="startEdit">
            <i data-feather="edit-2"></i>
          </button>
          <button class="dp__icon-btn" title="Закрыть (Esc)" @click="emit('close')">
            <i data-feather="x"></i>
          </button>
        </div>
      </div>
      <h2 class="dp__title">
        {{ isNew ? 'Новое правило' : eventTypeLabel || 'Правило' }}
      </h2>
      <div class="dp__badges" v-if="!isNew">
        <span :class="['badge', draft.is_enabled ? 'badge--status-active' : 'badge--status-former']">
          {{ draft.is_enabled ? 'включено' : 'выключено' }}
        </span>
        <span class="badge badge--neutral">приоритет {{ draft.priority }}</span>
      </div>
    </div>

    <div class="dp__body">
      <!-- EVENT -->
      <DrawerSection title="Событие">
        <div class="dp__field" v-if="editing">
          <select class="drawer-field__input" v-model="draft.event_type_id">
            <option :value="0" disabled>— выберите событие —</option>
            <option v-for="e in eventTypes" :key="e.id" :value="e.id">
              {{ e.label }} ({{ e.key }})
            </option>
          </select>
          <div class="drawer-field__hint" v-if="eventTypeSource">
            Источник: <code>{{ eventTypeSource }}</code>
          </div>
        </div>
        <div v-else>
          <div class="dp__value">{{ eventTypeLabel || '—' }}</div>
          <div class="dp__key" v-if="eventTypeKey">{{ eventTypeKey }}</div>
          <div class="drawer-field__hint" v-if="eventTypeSource">
            Источник: <code>{{ eventTypeSource }}</code>
          </div>
        </div>
      </DrawerSection>

      <!-- CHANNEL -->
      <DrawerSection title="Канал доставки">
        <div class="dp__field" v-if="editing">
          <select class="drawer-field__input" v-model="draft.channel_id">
            <option :value="0" disabled>— выберите канал —</option>
            <option v-for="c in channels" :key="c.id" :value="c.id">
              {{ c.kind === 'email' ? '✉ Email' : '✈ Telegram' }} — {{ c.label || c.kind }}
            </option>
          </select>
        </div>
        <div v-else class="dp__channel-row">
          <i :data-feather="channelKind === 'email' ? 'mail' : 'send'" class="dp__channel-icon"></i>
          <span>{{ selectedChannel?.label || (channelKind === 'email' ? 'Email' : 'Telegram') }}</span>
        </div>
      </DrawerSection>

      <!-- RECIPIENTS -->
      <DrawerSection title="Получатели">
        <!-- Email channel recipients -->
        <template v-if="channelKind === 'email'">
          <div class="dp__sub">Прямые email-адреса</div>
          <div class="dp__chips">
            <span v-for="(e, i) in draft.recipients.emails" :key="i" class="dp__chip">
              {{ e }}
              <button v-if="editing" type="button" @click="removeEmail(i)" class="dp__chip-x">×</button>
            </span>
            <div v-if="!draft.recipients.emails?.length && !editing" class="dp__empty-line">не указаны</div>
          </div>
          <div v-if="editing" class="dp__chip-add">
            <input class="drawer-field__input drawer-field__input--mono"
                   v-model="newEmail" placeholder="email@example.com"
                   @keyup.enter.prevent="addEmail" />
            <GhostBtn @click="addEmail">Добавить</GhostBtn>
          </div>

          <div class="dp__sub">Сотрудники (по email)</div>
          <div v-if="editing" class="dp__picker">
            <label v-for="e in employees" :key="e.id" class="dp__picker-item">
              <input type="checkbox"
                     :checked="draft.recipients.employee_ids?.includes(e.id)"
                     @change="toggleEmployee(e.id)" />
              <span>{{ e.name }} <small>{{ e.email || '—' }}</small></span>
            </label>
            <div v-if="!employees.length" class="dp__empty-line">Нет сотрудников</div>
          </div>
          <div v-else class="dp__inline-list">
            {{ draft.recipients.employee_ids?.length ? fmt(draft.recipients.employee_ids, employeeName) : 'не указаны' }}
          </div>

          <div class="dp__sub">Филиалы (все сотрудники филиала)</div>
          <div v-if="editing" class="dp__chip-row">
            <label v-for="b in branches" :key="b.id" class="dp__chip-toggle">
              <input type="checkbox"
                     :checked="draft.recipients.branch_ids?.includes(b.id)"
                     @change="toggleBranch(b.id)" />
              <span>{{ b.name }}</span>
            </label>
          </div>
          <div v-else class="dp__inline-list">
            {{ draft.recipients.branch_ids?.length ? fmt(draft.recipients.branch_ids, branchName) : 'не указаны' }}
          </div>
        </template>

        <!-- Telegram channel recipients -->
        <template v-else-if="channelKind === 'telegram'">
          <div class="dp__sub">Telegram-группы</div>
          <div v-if="editing" class="dp__chip-row">
            <label v-for="g in groups" :key="g.id" class="dp__chip-toggle">
              <input type="checkbox"
                     :checked="draft.recipients.telegram_group_ids?.includes(g.id)"
                     @change="toggleGroup(g.id)" />
              <span>{{ g.title || `chat_id=${g.chat_id}` }}</span>
            </label>
            <div v-if="!groups.length" class="dp__empty-line">
              Нет групп. Добавьте на вкладке «Группы».
            </div>
          </div>
          <div v-else class="dp__inline-list">
            {{ draft.recipients.telegram_group_ids?.length ? fmt(draft.recipients.telegram_group_ids, groupTitle) : 'не указаны' }}
          </div>
        </template>

        <div v-else class="drawer-field__hint">Выберите канал, чтобы указать получателей.</div>
      </DrawerSection>

      <!-- Settings -->
      <DrawerSection title="Параметры">
        <div class="dp__field">
          <label class="drawer-field__label">Приоритет</label>
          <input v-if="editing" class="drawer-field__input drawer-field__input--mono"
                 type="number" v-model.number="draft.priority" />
          <div v-else class="drawer-field__value drawer-field__value--mono">{{ draft.priority }}</div>
          <div class="drawer-field__hint">Меньше = выше. При нескольких правилах применяются по возрастанию.</div>
        </div>

        <div class="dp__check" v-if="editing">
          <label class="dp__check-label">
            <input type="checkbox" v-model="draft.is_enabled" />
            <span>Правило активно</span>
          </label>
        </div>
        <div v-else-if="!isNew && canManage" class="dp__toggle">
          <span>Правило активно</span>
          <button :class="['dp__switch', { 'dp__switch--on': draft.is_enabled }]" @click="toggleEnabled">
            <span class="dp__switch-knob"></span>
          </button>
        </div>
      </DrawerSection>

      <p v-if="error" class="dp__err">{{ error }}</p>

      <!-- Footer -->
      <div v-if="editing" class="dp__footer">
        <GhostBtn @click="cancelEdit" :disabled="saving">Отмена</GhostBtn>
        <button class="dp__primary" :disabled="saving" @click="save">
          <i data-feather="check"></i>
          {{ saving ? 'Сохраняю…' : 'Сохранить' }}
        </button>
      </div>

      <!-- Delete -->
      <DrawerSection v-if="!isNew && canManage && !editing" title="Опасная зона">
        <GhostBtn danger @click="remove" :disabled="saving">
          <i :data-feather="confirmDelete ? 'check' : 'trash-2'"></i>
          {{ confirmDelete ? 'Подтвердите ещё раз' : 'Удалить правило' }}
        </GhostBtn>
      </DrawerSection>
    </div>
  </aside>
</template>

<style scoped>
.dp {
  width: 460px; flex-shrink: 0;
  background: var(--bg); border-left: 1px solid var(--border);
  display: flex; flex-direction: column; align-self: stretch;
  overflow: auto; font-size: 13px;
}
.dp__header {
  padding: 18px 22px 14px; border-bottom: 1px solid var(--border-2);
  display: flex; flex-direction: column; gap: 10px;
}
.dp__header-top { display: flex; justify-content: space-between; align-items: center; }
.dp__eyebrow {
  font-size: 10px; letter-spacing: .16em; text-transform: uppercase;
  color: var(--text-4); font-family: 'JetBrains Mono', monospace;
}
.dp__header-actions { display: flex; gap: 4px; }
.dp__icon-btn {
  width: 30px; height: 30px; border: 0; border-radius: 7px;
  background: transparent; color: var(--text-2); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: background .15s;
}
.dp__icon-btn:hover { background: var(--panel); color: var(--text); }
.dp__icon-btn :deep(svg) { width: 15px; height: 15px; }
.dp__title { font-size: 22px; font-weight: 600; letter-spacing: -0.02em; margin: 0; color: var(--text); }
.dp__badges { display: flex; gap: 6px; flex-wrap: wrap; }

.dp__body {
  flex: 1; overflow-y: auto;
  padding: 18px 22px 24px;
  display: flex; flex-direction: column; gap: 22px;
}

.dp__field { display: flex; flex-direction: column; gap: 6px; }
.dp__value { font-size: 14px; color: var(--text); font-weight: 500; }
.dp__key { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-4); margin-top: -2px; }
.dp__channel-row { display: flex; align-items: center; gap: 8px; font-size: 14px; color: var(--text); }
.dp__channel-row :deep(svg) { width: 16px; height: 16px; color: var(--accent); }

.dp__sub {
  font-size: 11px; color: var(--text-3); font-weight: 500;
  margin-top: 8px;
}
.dp__sub:first-child { margin-top: 0; }
.dp__chips { display: flex; flex-wrap: wrap; gap: 6px; }
.dp__chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 10px; border-radius: 999px;
  background: var(--panel); border: 1px solid var(--border);
  font-size: 12px; color: var(--text);
}
.dp__chip-x {
  background: 0; border: 0; color: var(--text-3); cursor: pointer;
  font-size: 14px; padding: 0 2px;
}
.dp__chip-add { display: flex; gap: 8px; align-items: center; margin-top: 4px; }
.dp__chip-add input { flex: 1; min-width: 0; }

.dp__picker {
  max-height: 220px; overflow-y: auto;
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 6px;
}
.dp__picker-item {
  display: flex; align-items: center; gap: 8px; padding: 5px 6px;
  font-size: 13px; color: var(--text); cursor: pointer; border-radius: 6px;
}
.dp__picker-item:hover { background: var(--hover-bg); }
.dp__picker-item small { color: var(--text-4); font-size: 11px; }
.dp__picker-item input { accent-color: var(--accent); }
.dp__chip-row { display: flex; flex-wrap: wrap; gap: 6px; }
.dp__chip-toggle {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 10px; border-radius: 999px;
  border: 1px solid var(--border); background: var(--surface);
  cursor: pointer; font-size: 12px; color: var(--text);
  user-select: none;
}
.dp__chip-toggle:has(input:checked) {
  border-color: var(--accent); background: var(--ring); color: var(--text);
}
.dp__chip-toggle input { accent-color: var(--accent); }
.dp__empty-line { font-size: 12px; color: var(--placeholder); }
.dp__inline-list { font-size: 13px; color: var(--text-2); word-break: break-word; }

.dp__check-label {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; color: var(--text); cursor: pointer;
}
.dp__check-label input { accent-color: var(--accent); }

.dp__toggle {
  display: flex; align-items: center; justify-content: space-between;
  font-size: 13px; color: var(--text);
}
.dp__switch {
  width: 36px; height: 20px; border-radius: 999px;
  background: var(--border); border: 0; cursor: pointer; position: relative;
  transition: background .15s;
}
.dp__switch--on { background: var(--accent); }
.dp__switch-knob {
  position: absolute; top: 2px; left: 2px;
  width: 16px; height: 16px; background: var(--surface);
  border-radius: 50%; transition: transform .15s;
}
.dp__switch--on .dp__switch-knob { transform: translateX(16px); }

.dp__err {
  margin: 0; padding: 8px 12px;
  background: #fbe8e7; border: 1px solid #f3c5c2; border-radius: 8px;
  color: #b3261e; font-size: 12px;
}

.dp__footer {
  display: flex; gap: 8px; justify-content: flex-end;
  padding-top: 8px; border-top: 1px solid var(--border-2);
}
.dp__primary {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 9px 16px; border: 0; border-radius: 9px;
  background: var(--accent); color: var(--on-accent);
  font-size: 13px; font-weight: 500; cursor: pointer;
  font-family: inherit;
}
.dp__primary:disabled { opacity: .5; cursor: not-allowed; }
.dp__primary :deep(svg) { width: 14px; height: 14px; }

.badge {
  display: inline-flex; align-items: center;
  font-size: 11px; font-weight: 500; padding: 3px 8px; border-radius: 5px;
}
.badge--status-active { background: var(--status-active-bg); color: var(--status-active-fg); }
.badge--status-former { background: var(--panel); color: var(--text-3); }
.badge--neutral       { background: var(--panel); color: var(--text-2); }

.drawer-field__hint { font-size: 11px; color: var(--text-4); margin-top: 2px; }
.drawer-field__hint code { font-family: 'JetBrains Mono', monospace; background: var(--panel); padding: 1px 4px; border-radius: 3px; color: var(--text); }
.drawer-field__input {
  padding: 9px 12px; font-size: 13px;
  border: 1px solid var(--border-strong); border-radius: 8px;
  background: var(--surface); color: var(--text); font-family: inherit; outline: none;
}
.drawer-field__input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--ring); }
.drawer-field__input--mono { font-family: 'JetBrains Mono', monospace; }
.drawer-field__label { font-size: 10px; font-weight: 500; letter-spacing: .16em; text-transform: uppercase; color: var(--text-4); font-family: 'JetBrains Mono', monospace; }
.drawer-field__value { font-size: 13px; color: var(--text); }
.drawer-field__value--mono { font-family: 'JetBrains Mono', monospace; }
</style>
