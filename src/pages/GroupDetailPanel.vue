<script setup lang="ts">
import { ref, computed, watch, onMounted, onUpdated, nextTick } from 'vue'
import { usePortal } from '../composables/usePortal'
import { api } from '../api'
import DrawerSection from '../components/DrawerSection.vue'
import DrawerField from '../components/DrawerField.vue'
import GhostBtn from '../components/GhostBtn.vue'

declare const feather: any

interface Group {
  id: number; chat_id: number; title: string; chat_type: string;
  branch_id: number | null
  is_member: boolean; can_send: boolean
  last_seen_at: string | null; added_at: string
}

const props = defineProps<{
  group: Group
  canManage: boolean
}>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'updated'): void
  (e: 'deleted'): void
}>()

const { branches } = usePortal()

const editing = ref(false)
const saving = ref(false)
const draftTitle = ref(props.group.title)
const draftBranch = ref<number | null>(props.group.branch_id)
const checking = ref(false)
const checkResult = ref<string | null>(null)
const confirmDelete = ref(false)

watch(() => props.group, (g) => {
  draftTitle.value = g.title
  draftBranch.value = g.branch_id
  editing.value = false
  checkResult.value = null
}, { immediate: true })

onMounted(() => nextTick(() => feather?.replace()))
onUpdated(() => nextTick(() => feather?.replace()))

const branchOptions = computed(() =>
  branches.value.map(b => ({ value: b.id, label: b.name }))
)
const branchLabel = computed(() => {
  if (!props.group.branch_id) return ''
  return branches.value.find(b => b.id === props.group.branch_id)?.name || `#${props.group.branch_id}`
})

const statusBadge = computed(() => {
  const g = props.group
  if (!g.is_member) return { variant: 'status-error', label: 'не в чате' }
  if (!g.can_send)  return { variant: 'role',          label: 'без прав отправки' }
  return { variant: 'status-active', label: 'готов отправлять' }
})

function startEdit() {
  if (!props.canManage) return
  editing.value = true
}
function cancelEdit() {
  draftTitle.value = props.group.title
  draftBranch.value = props.group.branch_id
  editing.value = false
}
async function save() {
  saving.value = true
  try {
    const body: any = {}
    if (draftTitle.value !== props.group.title) body.title = draftTitle.value
    if (draftBranch.value !== props.group.branch_id) body.branch_id = draftBranch.value
    if (Object.keys(body).length) {
      await api.put(`/api/mailer/groups/${props.group.id}`, body)
      emit('updated')
    }
    editing.value = false
  } finally { saving.value = false }
}

async function check() {
  checking.value = true
  checkResult.value = null
  try {
    const res = await api.post(`/api/mailer/groups/${props.group.id}/check`, {}).then(r => r.data)
    checkResult.value = res.ok
      ? `OK · status=${res.tg_status}, ${res.is_member ? 'в чате' : 'не в чате'}${res.can_send ? ', можно слать' : ''}`
      : `Ошибка: ${res.error}`
    emit('updated')
  } catch (e: any) {
    checkResult.value = 'Ошибка: ' + (e?.response?.data?.error || e?.message || e)
  } finally { checking.value = false }
}

async function remove() {
  if (!confirmDelete.value) { confirmDelete.value = true; return }
  saving.value = true
  try {
    await api.delete(`/api/mailer/groups/${props.group.id}`)
    emit('deleted')
  } finally { saving.value = false }
}

function fmtDate(d: string | null): string {
  return d ? new Date(d).toLocaleString('ru-RU') : '—'
}
</script>

<template>
  <aside class="dp">
    <div class="dp__header">
      <div class="dp__header-top">
        <span class="dp__eyebrow">TELEGRAM GROUP</span>
        <div class="dp__header-actions">
          <button v-if="canManage && !editing" class="dp__icon-btn" title="Редактировать" @click="startEdit">
            <i data-feather="edit-2"></i>
          </button>
          <button class="dp__icon-btn" title="Закрыть (Esc)" @click="emit('close')">
            <i data-feather="x"></i>
          </button>
        </div>
      </div>
      <h2 class="dp__title">{{ group.title || '(без названия)' }}</h2>
      <div class="dp__badges">
        <span :class="['badge', `badge--${statusBadge.variant}`]">{{ statusBadge.label }}</span>
        <span class="badge badge--neutral">{{ group.chat_type }}</span>
      </div>
    </div>

    <div class="dp__body">
      <DrawerSection title="Идентификация">
        <DrawerField label="chat_id" :model-value="group.chat_id" :editing="false" mono />
        <DrawerField label="Название чата" v-model="draftTitle" :editing="editing"
                     placeholder="Например, «Отдел продаж»" />
      </DrawerSection>

      <DrawerSection title="Привязка к филиалу">
        <DrawerField
          label="Филиал"
          :model-value="editing ? draftBranch : branchLabel"
          @update:model-value="(v: any) => draftBranch = v ? Number(v) : null"
          :editing="editing"
          :options="branchOptions"
          placeholder="— не привязан —"
        />
        <div class="drawer-field__hint">
          При маршрутизации события с указанным <code>branch_id</code> будут уходить
          именно в эту группу.
        </div>
      </DrawerSection>

      <DrawerSection title="Статус бота">
        <template #action>
          <button v-if="canManage" class="dp__inline-btn" :disabled="checking" @click="check">
            <i data-feather="refresh-cw"></i>
            <span>{{ checking ? 'Проверяю…' : 'Проверить' }}</span>
          </button>
        </template>
        <div class="dp__stats">
          <div class="dp__stat-row">
            <span>В чате</span>
            <span :class="group.is_member ? 'dp__stat-val--ok' : 'dp__stat-val--err'">
              {{ group.is_member ? 'да' : 'нет' }}
            </span>
          </div>
          <div class="dp__stat-row">
            <span>Может писать</span>
            <span :class="group.can_send ? 'dp__stat-val--ok' : 'dp__stat-val--err'">
              {{ group.can_send ? 'да' : 'нет' }}
            </span>
          </div>
          <div class="dp__stat-row">
            <span>Последняя проверка</span>
            <span :class="['dp__stat-mono', { 'dp__stat-val--empty': !group.last_seen_at }]">
              {{ fmtDate(group.last_seen_at) }}
            </span>
          </div>
          <div class="dp__stat-row">
            <span>Добавлен</span>
            <span class="dp__stat-mono">{{ fmtDate(group.added_at) }}</span>
          </div>
        </div>
        <div v-if="checkResult" class="dp__inline-result">{{ checkResult }}</div>
      </DrawerSection>

      <!-- Footer (editing) -->
      <div v-if="editing" class="dp__footer">
        <GhostBtn @click="cancelEdit" :disabled="saving">Отмена</GhostBtn>
        <button class="dp__primary" :disabled="saving" @click="save">
          <i data-feather="check"></i>
          {{ saving ? 'Сохраняю…' : 'Сохранить' }}
        </button>
      </div>

      <!-- Delete -->
      <DrawerSection v-if="canManage && !editing" title="Опасная зона">
        <GhostBtn danger @click="remove" :disabled="saving">
          <i :data-feather="confirmDelete ? 'check' : 'trash-2'"></i>
          {{ confirmDelete ? 'Подтвердите ещё раз' : 'Удалить группу' }}
        </GhostBtn>
        <div class="drawer-field__hint">
          Запись удаляется, но история сообщений в журнале остаётся.
          Если бот всё ещё в чате — через ≤30с группа появится снова.
        </div>
      </DrawerSection>
    </div>
  </aside>
</template>

<style scoped>
.dp {
  width: 420px; flex-shrink: 0;
  background: var(--bg); border-left: 1px solid var(--border);
  display: flex; flex-direction: column; align-self: stretch;
  overflow: auto; font-size: 13px;
}

.dp__header {
  padding: 18px 22px 14px;
  border-bottom: 1px solid var(--border-2);
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
  transition: background .15s, color .15s;
}
.dp__icon-btn:hover { background: var(--panel); color: var(--text); }
.dp__icon-btn :deep(svg) { width: 15px; height: 15px; }

.dp__title { font-size: 22px; font-weight: 600; letter-spacing: -0.02em; margin: 0; color: var(--text); word-break: break-word; }
.dp__badges { display: flex; gap: 6px; flex-wrap: wrap; }

.dp__body {
  flex: 1; overflow-y: auto;
  padding: 18px 22px 24px;
  display: flex; flex-direction: column; gap: 22px;
}

.dp__stats { display: flex; flex-direction: column; gap: 6px; }
.dp__stat-row {
  display: flex; justify-content: space-between; align-items: baseline;
  font-size: 12px;
}
.dp__stat-row > span:first-child { color: var(--text-3); }
.dp__stat-val--ok    { color: var(--status-active-fg); font-weight: 500; }
.dp__stat-val--err   { color: var(--danger); font-weight: 500; }
.dp__stat-val--empty { color: var(--placeholder); }
.dp__stat-mono       { font-family: 'JetBrains Mono', monospace; color: var(--text-2); }

.dp__inline-btn {
  border: 0; background: transparent; color: var(--accent);
  font-size: 12px; cursor: pointer; padding: 2px 6px;
  display: inline-flex; align-items: center; gap: 4px; font-family: inherit;
}
.dp__inline-btn:disabled { opacity: .55; cursor: not-allowed; }
.dp__inline-btn:hover:not(:disabled) { text-decoration: underline; }
.dp__inline-btn :deep(svg) { width: 12px; height: 12px; }

.dp__inline-result {
  margin-top: -4px; padding: 8px 10px;
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 7px; font-size: 12px; color: var(--text-2);
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
  font-family: inherit; transition: opacity .15s;
}
.dp__primary:disabled { opacity: .5; cursor: not-allowed; }
.dp__primary :deep(svg) { width: 14px; height: 14px; }

.badge {
  display: inline-flex; align-items: center;
  font-size: 11px; font-weight: 500; padding: 3px 8px; border-radius: 5px;
}
.badge--status-active { background: var(--status-active-bg); color: var(--status-active-fg); }
.badge--role          { background: var(--role-bg); color: var(--role-fg); }
.badge--neutral       { background: var(--panel); color: var(--text-2); }
.badge--status-error  { background: #fbe8e7; color: #b3261e; }

.drawer-field__hint { font-size: 11px; color: var(--text-4); }
.drawer-field__hint code { font-family: 'JetBrains Mono', monospace; background: var(--panel); padding: 1px 4px; border-radius: 3px; color: var(--text); }
</style>
