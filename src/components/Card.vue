<script setup lang="ts">
// Generic surface card — title (optional), optional eyebrow + action slot,
// body slot. All colors via design tokens so it reskinns with theme.
defineProps<{
  title?: string
  eyebrow?: string
  /** Override default surface variant: 'surface' (default) or 'panel'. */
  variant?: 'surface' | 'panel'
}>()
</script>

<template>
  <section :class="['card', variant === 'panel' ? 'card--panel' : 'card--surface']">
    <header v-if="title || eyebrow || $slots.action" class="card__head">
      <div class="card__head-text">
        <div v-if="eyebrow" class="card__eyebrow">{{ eyebrow }}</div>
        <div v-if="title" class="card__title">{{ title }}</div>
      </div>
      <div v-if="$slots.action" class="card__action">
        <slot name="action" />
      </div>
    </header>
    <div class="card__body"><slot /></div>
  </section>
</template>

<style scoped>
.card {
  border-radius: 12px;
  padding: 16px 18px;
  margin-bottom: 14px;
}
.card--surface {
  background: var(--surface);
  border: 1px solid var(--border-2, var(--border));
}
.card--panel {
  background: var(--panel);
  border: 1px solid var(--border);
}

.card__head {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.card__head-text { min-width: 0; }
.card__eyebrow {
  font-size: 10px;
  letter-spacing: .16em;
  text-transform: uppercase;
  color: var(--text-4);
  font-weight: 500;
  margin-bottom: 4px;
}
.card__title {
  font-size: 15px; font-weight: 600;
  color: var(--text);
  letter-spacing: -0.005em;
}
.card__action { flex-shrink: 0; }

.card__body { color: var(--text); font-size: 13px; }
.card__body :deep(p) { margin: 4px 0; line-height: 1.5; }
.card__body :deep(p:first-child) { margin-top: 0; }
.card__body :deep(p:last-child) { margin-bottom: 0; }
</style>
