<script setup lang="ts">
defineProps<{
  variant?: 'primary' | 'ghost'
  icon?: string         // feather icon name
  danger?: boolean
  disabled?: boolean
}>()
</script>

<template>
  <button
    :class="['btn',
             variant === 'primary' ? 'btn--primary' : 'btn--ghost',
             { 'btn--danger': danger, 'btn--disabled': disabled }]"
    :disabled="disabled"
  >
    <i v-if="icon" :data-feather="icon" class="btn__icon"></i>
    <slot />
  </button>
</template>

<style scoped>
.btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 9px 16px;
  border-radius: 9px;
  font-size: 13px; font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  border: 1px solid transparent;
  transition: background .12s, border-color .12s, color .12s, opacity .12s;
}
.btn:disabled, .btn--disabled { opacity: .55; cursor: not-allowed; }

.btn--primary {
  background: var(--accent);
  color: var(--on-accent);
  border-color: var(--accent);
}
.btn--primary:hover:not(:disabled) { filter: brightness(1.05); }

.btn--ghost {
  background: var(--surface);
  color: var(--text);
  border-color: var(--border);
}
.btn--ghost:hover:not(:disabled) { background: var(--panel); }

.btn--danger.btn--ghost { color: var(--danger); }
.btn--danger.btn--ghost:hover:not(:disabled) { background: rgba(211, 55, 45, .08); }

.btn__icon { width: 14px; height: 14px; }
.btn :deep(svg) { width: 14px; height: 14px; }
</style>
