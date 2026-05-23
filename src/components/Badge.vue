<script setup lang="ts">
defineProps<{
  variant?: 'status-active' | 'status-former' | 'role' | 'neutral' | 'root' | 'count'
}>()
</script>

<template>
  <span :class="['badge', `badge--${variant || 'neutral'}`]">
    <slot />
  </span>
</template>

<style scoped>
.badge {
  display: inline-flex; align-items: center;
  font-size: 11px; font-weight: 500;
  padding: 3px 8px;
  border-radius: 5px;
  white-space: nowrap;
  line-height: 1.3;
}

.badge--status-active {
  background: var(--status-active-bg);
  color: var(--status-active-fg);
}
.badge--status-former {
  background: var(--panel);
  color: var(--text-3);
}
.badge--role {
  background: var(--role-bg);
  color: var(--role-fg);
}
.badge--neutral {
  background: var(--panel);
  color: var(--text-2);
}
.badge--root {
  background: var(--accent);
  color: var(--on-accent);
  font-family: 'JetBrains Mono', monospace;
  letter-spacing: .08em;
}
.badge--count {
  background: var(--panel);
  color: var(--text-2);
  font-family: 'JetBrains Mono', monospace;
}
</style>
