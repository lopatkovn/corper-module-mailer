<script setup lang="ts">
defineProps<{ title?: string }>()
</script>

<template>
  <div class="drawer-section">
    <div v-if="title || $slots.action" class="drawer-section__head">
      <span v-if="title" class="drawer-section__title">{{ title }}</span>
      <slot name="action" />
    </div>
    <div class="drawer-section__body">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.drawer-section {
  display: flex; flex-direction: column;
  gap: 14px;
}
.drawer-section__head {
  display: flex; justify-content: space-between; align-items: baseline;
}
.drawer-section__title {
  font-size: 10px; font-weight: 500;
  letter-spacing: .16em;
  text-transform: uppercase;
  color: var(--text-2);
  font-family: 'JetBrains Mono', monospace;
}
.drawer-section__body {
  display: flex; flex-direction: column;
  gap: 12px;
}
</style>
