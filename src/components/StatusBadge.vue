<script setup lang="ts">
defineProps<{ status: 'ok' | 'untested' | 'error' | 'unconfigured' | string }>()

const LABELS: Record<string, string> = {
  ok: 'Готов',
  untested: 'Не проверен',
  error: 'Ошибка',
  unconfigured: 'Не настроен',
}
</script>

<template>
  <span :class="['status', `status--${status}`]">
    <span class="status__dot"></span>
    {{ LABELS[status] || status }}
  </span>
</template>

<style scoped>
.status {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 11px; font-weight: 500;
  letter-spacing: .02em;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-3);
}
.status__dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--text-4);
}
.status--ok           { color: #0a7d3e; border-color: #b6e3c2; background: #e7f6ec; }
.status--ok .status__dot           { background: #1aae5b; }
.status--untested     { color: #8a6d10; border-color: #f0e2a3; background: #fcf6dd; }
.status--untested .status__dot     { background: #d9a417; }
.status--error        { color: #b3261e; border-color: #f3c5c2; background: #fbe8e7; }
.status--error .status__dot        { background: #d3372d; }
.status--unconfigured { color: var(--text-3); }
</style>
