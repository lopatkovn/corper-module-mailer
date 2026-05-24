<script setup lang="ts">
import { ref, computed, watch, onMounted, onUpdated, nextTick, onUnmounted } from 'vue'
import { usePortal } from '../composables/usePortal'
import { api } from '../api'
import DrawerSection from '../components/DrawerSection.vue'
import GhostBtn from '../components/GhostBtn.vue'

declare const feather: any

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

const props = defineProps<{
  rule: Rule | null
  isNew: boolean
  eventTypes: EventType[]
  groups: Group[]
  topicsByGroup: Record<number, Topic[]>
  canManage: boolean
}>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved', rule: Rule): void
  (e: 'deleted'): void
  (e: 'topics-reloaded'): void
}>()

const { branches } = usePortal()

const draft = ref<Rule>({
  id: 0,
  event_type_id: 0,
  branch_id: null,
  telegram_group_id: 0,
  topic_id: null,
  is_enabled: true,
  priority: 100,
})
const editing = ref(false)
const saving = ref(false)
const error = ref('')
const confirmDelete = ref(false)

// Topic-wizard state
const wizardOpen = ref(false)
const wizardName = ref('')
const wizardPhrase = ref('')
const wizardRegId = ref<number | null>(null)
const wizardExpires = ref<string | null>(null)
const wizardError = ref('')
const wizardGenerating = ref(false)
let wizardPollTimer: ReturnType<typeof setInterval> | null = null

watch(() => [props.rule, props.isNew], () => {
  if (props.isNew) {
    draft.value = {
      id: 0,
      event_type_id: props.eventTypes[0]?.id || 0,
      branch_id: null,
      telegram_group_id: props.groups[0]?.id || 0,
      topic_id: null,
      is_enabled: true,
      priority: 100,
    }
    editing.value = true
  } else if (props.rule) {
    draft.value = { ...props.rule }
    editing.value = false
  }
  error.value = ''
  confirmDelete.value = false
  closeWizard()
}, { immediate: true, deep: true })

onMounted(() => nextTick(() => feather?.replace()))
onUpdated(() => nextTick(() => feather?.replace()))
onUnmounted(() => { if (wizardPollTimer) clearInterval(wizardPollTimer) })

const eventTypeKey = computed(() => props.eventTypes.find(e => e.id === draft.value.event_type_id)?.key || '')
const eventTypeLabel = computed(() => props.eventTypes.find(e => e.id === draft.value.event_type_id)?.label || '')
const eventTypeSource = computed(() => props.eventTypes.find(e => e.id === draft.value.event_type_id)?.source_module || '')

const selectedGroup = computed(() => props.groups.find(g => g.id === draft.value.telegram_group_id))
const topicsForGroup = computed(() => props.topicsByGroup[draft.value.telegram_group_id] || [])

function startEdit() {
  if (!props.canManage) return
  editing.value = true
  error.value = ''
}
function cancelEdit() {
  if (props.isNew) { emit('close'); return }
  if (props.rule) draft.value = { ...props.rule }
  editing.value = false
  error.value = ''
}

async function save() {
  if (!draft.value.event_type_id || !draft.value.telegram_group_id) {
    error.value = 'Выберите событие и группу'
    return
  }
  saving.value = true
  error.value = ''
  try {
    const payload = {
      event_type_id: draft.value.event_type_id,
      branch_id: draft.value.branch_id,
      telegram_group_id: draft.value.telegram_group_id,
      topic_id: draft.value.topic_id,
      is_enabled: draft.value.is_enabled,
      priority: draft.value.priority,
    }
    let result: Rule
    if (props.isNew) {
      result = await api.post('/api/mailer/rules', payload).then(r => r.data)
    } else {
      result = await api.put(`/api/mailer/rules/${draft.value.id}`, payload).then(r => r.data)
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

// ── Topic wizard ──
function openWizard() {
  if (!draft.value.telegram_group_id) return
  wizardOpen.value = true
  wizardName.value = ''
  wizardPhrase.value = ''
  wizardRegId.value = null
  wizardExpires.value = null
  wizardError.value = ''
}
function closeWizard() {
  wizardOpen.value = false
  if (wizardPollTimer) { clearInterval(wizardPollTimer); wizardPollTimer = null }
}

async function generatePhrase() {
  wizardGenerating.value = true
  wizardError.value = ''
  try {
    const res = await api.post(
      `/api/mailer/groups/${draft.value.telegram_group_id}/topic-registrations`,
      { name: wizardName.value.trim() || undefined }
    ).then(r => r.data)
    wizardPhrase.value = res.phrase
    wizardRegId.value = res.id
    wizardExpires.value = res.expires_at
    if (wizardPollTimer) clearInterval(wizardPollTimer)
    wizardPollTimer = setInterval(pollRegistration, 3000)
  } catch (e: any) {
    wizardError.value = e?.response?.data?.error || e.message
  } finally { wizardGenerating.value = false }
}

async function pollRegistration() {
  if (!wizardRegId.value) return
  try {
    const res = await api.get(`/api/mailer/topic-registrations/${wizardRegId.value}`).then(r => r.data)
    if (res.consumed_at && res.topic?.id) {
      emit('topics-reloaded')
      draft.value.topic_id = res.topic.id
      closeWizard()
    } else if (res.expires_at && new Date(res.expires_at) < new Date()) {
      wizardError.value = 'Фраза просрочена. Попробуйте ещё раз.'
      if (wizardPollTimer) { clearInterval(wizardPollTimer); wizardPollTimer = null }
    }
  } catch {
    // ignore transient
  }
}

async function copyPhrase() {
  try {
    await navigator.clipboard.writeText(wizardPhrase.value)
  } catch { /* ignore */ }
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

      <!-- BRANCH FILTER -->
      <DrawerSection title="Фильтр по филиалу">
        <div class="dp__field" v-if="editing">
          <select class="drawer-field__input" :value="draft.branch_id ?? ''"
                  @change="draft.branch_id = ($event.target as HTMLSelectElement).value ? Number(($event.target as HTMLSelectElement).value) : null">
            <option value="">Любой филиал</option>
            <option v-for="b in branches" :key="b.id" :value="b.id">{{ b.name }}</option>
          </select>
          <div class="drawer-field__hint">
            Если задан — событие сматчится только когда <code>branch_id</code> в payload совпадёт с этим филиалом
            (либо когда в payload нет <code>branch_id</code> и в правиле <code>branch_id</code>=null).
          </div>
        </div>
        <div v-else>
          <div class="dp__value" v-if="draft.branch_id">
            {{ branches.find(b => b.id === draft.branch_id)?.name || `#${draft.branch_id}` }}
          </div>
          <div class="dp__muted" v-else>любой филиал</div>
        </div>
      </DrawerSection>

      <!-- TG GROUP -->
      <DrawerSection title="Telegram-группа">
        <div class="dp__field" v-if="editing">
          <select class="drawer-field__input" v-model="draft.telegram_group_id"
                  @change="draft.topic_id = null">
            <option :value="0" disabled>— выберите группу —</option>
            <option v-for="g in groups" :key="g.id" :value="g.id">
              {{ g.title || `chat ${g.chat_id}` }}
            </option>
          </select>
        </div>
        <div v-else>
          <div class="dp__channel-row">
            <i data-feather="message-square" class="dp__channel-icon"></i>
            <span>{{ selectedGroup?.title || (selectedGroup ? `chat ${selectedGroup.chat_id}` : '—') }}</span>
          </div>
        </div>
      </DrawerSection>

      <!-- TOPIC -->
      <DrawerSection title="Топик в группе">
        <template #action v-if="editing && draft.telegram_group_id">
          <button class="dp__inline-btn" @click="openWizard">
            <i data-feather="plus"></i>
            <span>Привязать новый</span>
          </button>
        </template>
        <div class="dp__field" v-if="editing">
          <select class="drawer-field__input" :value="draft.topic_id ?? ''"
                  @change="draft.topic_id = ($event.target as HTMLSelectElement).value ? Number(($event.target as HTMLSelectElement).value) : null">
            <option value="">Общий чат (без топика)</option>
            <option v-for="t in topicsForGroup" :key="t.id" :value="t.id">
              {{ t.name }}
            </option>
          </select>
          <div class="drawer-field__hint" v-if="!topicsForGroup.length">
            У этой группы пока нет зарегистрированных топиков. Нажмите
            «Привязать новый» — мы сгенерируем фразу, вы вставите её
            в нужный форум-топик, бот распознает и зарегистрирует.
          </div>
        </div>
        <div v-else>
          <div v-if="draft.topic_id" class="dp__value">
            <i data-feather="hash" class="dp__inline-icon"></i>
            {{ topicsForGroup.find(t => t.id === draft.topic_id)?.name || `#${draft.topic_id}` }}
          </div>
          <div v-else class="dp__muted">общий чат (без топика)</div>
        </div>
      </DrawerSection>

      <!-- Settings -->
      <DrawerSection title="Параметры">
        <div class="dp__field">
          <label class="drawer-field__label">Приоритет</label>
          <input v-if="editing" class="drawer-field__input drawer-field__input--mono"
                 type="number" v-model.number="draft.priority" />
          <div v-else class="drawer-field__value drawer-field__value--mono">{{ draft.priority }}</div>
          <div class="drawer-field__hint">Меньше = выше. Правила применяются по возрастанию.</div>
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

    <!-- Topic wizard modal -->
    <div v-if="wizardOpen" class="modal-bg" @click.self="closeWizard">
      <div class="modal">
        <h3 class="modal__title">Привязать новый топик</h3>

        <template v-if="!wizardPhrase">
          <div class="drawer-field">
            <label class="drawer-field__label">Название топика (опц.)</label>
            <input class="drawer-field__input" v-model="wizardName"
                   placeholder="Например, «Поддержка»" />
            <div class="drawer-field__hint">
              Можно оставить пустым — бот возьмёт «Топик #N».
            </div>
          </div>
          <p v-if="wizardError" class="modal__err">{{ wizardError }}</p>
          <div class="modal__actions">
            <GhostBtn @click="closeWizard">Отмена</GhostBtn>
            <button class="dp__primary" :disabled="wizardGenerating" @click="generatePhrase">
              {{ wizardGenerating ? 'Генерирую…' : 'Сгенерировать фразу' }}
            </button>
          </div>
        </template>

        <template v-else>
          <div class="modal__step">Шаг 1 — копируем фразу:</div>
          <div class="modal__phrase">
            <code>{{ wizardPhrase }}</code>
            <button class="modal__copy" @click="copyPhrase" title="Скопировать">
              <i data-feather="copy"></i>
            </button>
          </div>
          <div class="modal__step">Шаг 2 — открываем нужный форум-топик в Telegram и вставляем эту фразу сообщением:</div>
          <div class="modal__hint">
            Бот увидит сообщение с фразой → закрепит этот топик за рассылками →
            это окно закроется автоматически, топик станет выбранным.
          </div>
          <div class="modal__waiting">
            <i data-feather="loader" class="modal__spin"></i>
            <span>Ждём бота…</span>
          </div>
          <p v-if="wizardError" class="modal__err">{{ wizardError }}</p>
          <div class="modal__actions">
            <GhostBtn @click="closeWizard">Отмена</GhostBtn>
          </div>
        </template>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.dp {
  width: 460px; flex-shrink: 0;
  background: var(--bg); border-left: 1px solid var(--border);
  display: flex; flex-direction: column; align-self: stretch;
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  scrollbar-color: var(--scrollbar, var(--border-strong)) transparent; font-size: 13px;
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
.dp__value { font-size: 14px; color: var(--text); font-weight: 500; display: inline-flex; align-items: center; gap: 6px; }
.dp__key { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-4); margin-top: -2px; }
.dp__muted { color: var(--placeholder); font-size: 13px; }
.dp__channel-row { display: flex; align-items: center; gap: 8px; font-size: 14px; color: var(--text); }
.dp__channel-row :deep(svg) { width: 16px; height: 16px; color: var(--accent); }
.dp__inline-icon { width: 14px; height: 14px; color: var(--text-4); }
.dp__inline-icon :deep(svg) { width: 14px; height: 14px; }

.dp__inline-btn {
  border: 0; background: transparent; color: var(--accent);
  font-size: 12px; cursor: pointer; padding: 2px 6px;
  display: inline-flex; align-items: center; gap: 4px; font-family: inherit;
}
.dp__inline-btn:disabled { opacity: .55; cursor: not-allowed; }
.dp__inline-btn:hover:not(:disabled) { text-decoration: underline; }
.dp__inline-btn :deep(svg) { width: 12px; height: 12px; }

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

/* Topic wizard modal */
.modal-bg {
  position: fixed; inset: 0; background: rgba(0,0,0,.35);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.modal {
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 22px; min-width: 420px; max-width: 520px;
  box-shadow: 0 10px 40px rgba(0,0,0,.16);
}
.modal__title { margin: 0 0 14px; font-size: 16px; font-weight: 600; color: var(--text); }
.modal__step { font-size: 12px; color: var(--text-3); margin-top: 12px; margin-bottom: 6px; }
.modal__step:first-child { margin-top: 0; }
.modal__phrase {
  display: flex; align-items: center; gap: 8px;
  padding: 12px 14px;
  background: var(--panel); border: 1px dashed var(--border-strong); border-radius: 9px;
  font-family: 'JetBrains Mono', monospace; font-size: 14px;
  color: var(--text); font-weight: 600;
}
.modal__phrase code { flex: 1; user-select: all; }
.modal__copy {
  width: 30px; height: 30px; border: 1px solid var(--border); border-radius: 7px;
  background: var(--surface); color: var(--text-2); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
}
.modal__copy:hover { background: var(--hover-bg); color: var(--text); }
.modal__copy :deep(svg) { width: 14px; height: 14px; }
.modal__hint { font-size: 12px; color: var(--text-3); line-height: 1.5; margin: 8px 0 12px; }
.modal__waiting {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 12px;
  background: var(--panel); border-radius: 8px;
  font-size: 12px; color: var(--text-2);
}
.modal__waiting :deep(svg) { width: 14px; height: 14px; }
.modal__spin :deep(svg) { animation: spin 1.2s linear infinite; }
@keyframes spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }
.modal__err {
  margin: 12px 0 0; padding: 8px 12px;
  background: #fbe8e7; border: 1px solid #f3c5c2; border-radius: 8px;
  color: #b3261e; font-size: 12px;
}
.modal__actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 14px; }

.dp::-webkit-scrollbar { width: 8px; }
.dp::-webkit-scrollbar-track { background: transparent; }
.dp::-webkit-scrollbar-thumb {
  background: var(--scrollbar, var(--border-strong));
  border-radius: 6px;
  border: 2px solid transparent;
  background-clip: padding-box;
}
</style>
