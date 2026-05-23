<script setup lang="ts">
import { onMounted, onBeforeUnmount, nextTick, onUpdated, watch } from 'vue'

interface Badge { label: string; variant?: string }

const props = withDefaults(defineProps<{
  open: boolean
  eyebrow?: string
  title: string
  badges?: Badge[]
  editing?: boolean
  width?: number
  // When true, show edit pencil in header (calls @edit when clicked).
  editable?: boolean
  // When true, footer renders with Cancel/Save (+ optional Delete).
  footer?: boolean
  // Show the Delete button in footer (left side).
  deletable?: boolean
  saving?: boolean
}>(), {
  width: 420,
  editing: false,
  editable: false,
  footer: false,
  deletable: false,
  saving: false,
})

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'edit'): void
  (e: 'save'): void
  (e: 'cancel'): void
  (e: 'delete'): void
}>()

declare const feather: any

function onKey(e: KeyboardEvent) {
  if (!props.open) return
  if (e.key === 'Escape') {
    if (props.editing) emit('cancel')
    else emit('close')
  }
}

onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
onUpdated(() => feather?.replace())
watch(() => props.open, () => nextTick(() => feather?.replace()))
</script>

<template>
  <aside
    class="drawer"
    :class="{ 'drawer--open': open }"
    :style="{ width: open ? `${width}px` : '0px' }"
  >
    <div class="drawer__inner" :style="{ width: `${width}px` }">
      <!-- Header -->
      <div class="drawer__header">
        <div class="drawer__header-top">
          <span class="drawer__eyebrow">{{ eyebrow || ' ' }}</span>
          <div class="drawer__header-actions">
            <button
              v-if="editable && !editing"
              class="drawer__icon-btn"
              title="Редактировать"
              @click="emit('edit')"
            ><i data-feather="edit-2"></i></button>
            <button
              class="drawer__icon-btn"
              title="Закрыть (Esc)"
              @click="emit('close')"
            ><i data-feather="x"></i></button>
          </div>
        </div>
        <h2 class="drawer__title">{{ title }}</h2>
        <div v-if="badges && badges.length" class="drawer__badges">
          <slot name="badges">
            <span
              v-for="(b, i) in badges"
              :key="i"
              :class="['badge', `badge--${b.variant || 'neutral'}`]"
            >{{ b.label }}</span>
          </slot>
        </div>
      </div>

      <!-- Body -->
      <div class="drawer__body">
        <slot />
      </div>

      <!-- Footer (edit-mode) -->
      <div v-if="footer && editing" class="drawer__footer">
        <button
          v-if="deletable"
          class="drawer__delete"
          @click="emit('delete')"
        >
          <i data-feather="trash-2"></i>
          Удалить
        </button>
        <div class="drawer__footer-right">
          <button class="drawer__cancel" :disabled="saving" @click="emit('cancel')">Отмена</button>
          <button class="drawer__save" :disabled="saving" @click="emit('save')">
            {{ saving ? 'Сохранение…' : 'Сохранить' }}
          </button>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.drawer {
  /* Width is animated via inline style; everything inside has fixed width */
  flex-shrink: 0;
  background: var(--bg);
  border-left: 1px solid var(--border);
  transition: width .22s ease;
  overflow: hidden;
  display: flex; flex-direction: column;
  align-self: stretch;
}
.drawer:not(.drawer--open) { border-left: none; }
.drawer__inner {
  display: flex; flex-direction: column;
  height: 100%;
}

/* Header */
.drawer__header {
  padding: 18px 22px 14px;
  border-bottom: 1px solid var(--border-2);
  display: flex; flex-direction: column;
  gap: 10px;
  flex-shrink: 0;
}
.drawer__header-top {
  display: flex; justify-content: space-between; align-items: center;
}
.drawer__eyebrow {
  font-size: 10px;
  letter-spacing: .16em;
  text-transform: uppercase;
  color: var(--text-4);
  font-family: 'JetBrains Mono', monospace;
}
.drawer__header-actions {
  display: flex; gap: 4px;
}
.drawer__icon-btn {
  width: 30px; height: 30px;
  border: 0; border-radius: 7px;
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: background .15s, color .15s;
}
.drawer__icon-btn:hover { background: var(--panel); color: var(--text); }
.drawer__icon-btn :deep(svg) { width: 15px; height: 15px; }

.drawer__title {
  font-size: 22px; font-weight: 600;
  letter-spacing: -0.02em;
  margin: 0;
  color: var(--text);
  word-break: break-word;
}
.drawer__badges {
  display: flex; gap: 6px; flex-wrap: wrap;
}
.drawer__badges :deep(.badge) {
  display: inline-flex; align-items: center;
  font-size: 11px; font-weight: 500;
  padding: 3px 8px;
  border-radius: 5px;
  white-space: nowrap;
}
.drawer__badges :deep(.badge--status-active) { background: var(--status-active-bg); color: var(--status-active-fg); }
.drawer__badges :deep(.badge--status-former) { background: var(--panel); color: var(--text-3); }
.drawer__badges :deep(.badge--role) { background: var(--role-bg); color: var(--role-fg); }
.drawer__badges :deep(.badge--neutral) { background: var(--panel); color: var(--text-2); }
.drawer__badges :deep(.badge--root) { background: var(--accent); color: var(--on-accent); font-family: 'JetBrains Mono', monospace; letter-spacing: .08em; }

/* Body */
.drawer__body {
  flex: 1;
  overflow-y: auto;
  padding: 18px 22px 24px;
  display: flex; flex-direction: column;
  gap: 22px;
}
.drawer__body::-webkit-scrollbar { width: 6px; }
.drawer__body::-webkit-scrollbar-thumb { background: var(--scrollbar); border-radius: 6px; }

/* Footer (edit-mode) */
.drawer__footer {
  padding: 14px 22px;
  border-top: 1px solid var(--border-2);
  display: flex; gap: 8px;
  align-items: center;
  background: var(--bg);
  flex-shrink: 0;
}
.drawer__delete {
  padding: 8px 10px;
  border-radius: 8px;
  border: 0;
  background: transparent;
  color: var(--danger);
  cursor: pointer;
  display: flex; align-items: center; gap: 6px;
  font-size: 13px;
  font-family: inherit;
  transition: background .15s;
}
.drawer__delete:hover { background: var(--ring); }
.drawer__delete :deep(svg) { width: 14px; height: 14px; }
.drawer__footer-right {
  margin-left: auto;
  display: flex; gap: 8px;
}
.drawer__cancel {
  padding: 8px 14px;
  border-radius: 9px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  font-size: 13px; font-weight: 500;
  cursor: pointer;
  font-family: inherit;
  transition: background .15s;
}
.drawer__cancel:hover:not(:disabled) { background: var(--hover-bg); }
.drawer__cancel:disabled { opacity: .5; cursor: not-allowed; }
.drawer__save {
  padding: 8px 16px;
  border-radius: 9px;
  border: 0;
  background: var(--accent);
  color: var(--on-accent);
  font-size: 13px; font-weight: 500;
  cursor: pointer;
  font-family: inherit;
  transition: opacity .15s;
}
.drawer__save:hover:not(:disabled) { opacity: .9; }
.drawer__save:disabled { opacity: .5; cursor: not-allowed; }
</style>
