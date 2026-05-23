<script setup lang="ts">
defineProps<{ danger?: boolean; disabled?: boolean }>()
</script>

<template>
  <button :class="['ghost-btn', { 'ghost-btn--danger': danger }]" :disabled="disabled">
    <slot />
  </button>
</template>

<style scoped>
.ghost-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 14px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface);
  color: var(--text);
  font-size: 13px; font-weight: 500;
  cursor: pointer;
  font-family: inherit;
  transition: background .15s, border-color .15s;
}
.ghost-btn:hover:not(:disabled) { background: var(--hover-bg); }
.ghost-btn:disabled { opacity: .5; cursor: not-allowed; }
.ghost-btn :deep(svg) { width: 14px; height: 14px; }
.ghost-btn--danger { color: var(--danger); }
</style>
