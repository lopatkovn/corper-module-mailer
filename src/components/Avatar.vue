<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  name?: string | null
  tone?: string | null
  size?: number
  sq?: boolean
}>(), {
  size: 32,
  sq: false,
})

function initialsOf(n: string): string {
  return n.trim().split(/\s+/).slice(0, 2).map(p => p[0] || '').join('').toUpperCase()
}

const initials = computed(() => props.name ? initialsOf(props.name) : '')
const radius = computed(() => props.sq ? '8px' : '50%')
const fontSize = computed(() => `${Math.round(props.size * 0.34)}px`)
</script>

<template>
  <div
    class="avatar"
    :class="{ 'avatar--empty': !name }"
    :style="{
      width: `${size}px`, height: `${size}px`,
      borderRadius: radius,
      background: name ? (tone || '#7B6FE0') : 'var(--border-2)',
      color: name ? 'var(--surface)' : 'var(--text-4)',
      fontSize,
    }"
  >{{ initials || '—' }}</div>
</template>

<style scoped>
.avatar {
  display: inline-flex; align-items: center; justify-content: center;
  font-weight: 600;
  letter-spacing: .02em;
  flex-shrink: 0;
  user-select: none;
}
.avatar--empty { font-weight: 500; }
</style>
