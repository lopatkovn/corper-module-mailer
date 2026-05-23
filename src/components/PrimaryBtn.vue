<script setup lang="ts">
defineProps<{ disabled?: boolean }>()
</script>

<template>
  <button class="primary-btn" :disabled="disabled">
    <slot name="icon">
      <i data-feather="plus"></i>
    </slot>
    <slot />
  </button>
</template>

<style scoped>
.primary-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 9px 16px;
  border: 0; border-radius: 9px;
  background: var(--accent); color: var(--on-accent);
  font-size: 13px; font-weight: 500;
  cursor: pointer;
  font-family: inherit;
  transition: opacity .15s, transform .1s;
}
.primary-btn:hover:not(:disabled) { opacity: .9; }
.primary-btn:active:not(:disabled) { transform: scale(.98); }
.primary-btn:disabled { opacity: .5; cursor: not-allowed; }
.primary-btn :deep(svg) { width: 14px; height: 14px; }
</style>
