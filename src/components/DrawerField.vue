<script setup lang="ts">
interface Option { value: any; label: string }

defineProps<{
  label: string
  modelValue?: any
  editing?: boolean
  type?: string
  mono?: boolean
  placeholder?: string
  options?: Option[]
  hint?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: any): void
}>()
</script>

<template>
  <div class="drawer-field">
    <label class="drawer-field__label">{{ label }}</label>

    <template v-if="editing">
      <select
        v-if="options"
        class="drawer-field__input"
        :value="modelValue || ''"
        @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
      >
        <option value="">— не выбрано —</option>
        <option v-for="o in options" :key="String(o.value)" :value="o.value">{{ o.label }}</option>
      </select>
      <input
        v-else
        class="drawer-field__input"
        :class="{ 'drawer-field__input--mono': mono }"
        :type="type || 'text'"
        :value="modelValue || ''"
        :placeholder="placeholder"
        @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      />
    </template>

    <div
      v-else
      class="drawer-field__value"
      :class="{ 'drawer-field__value--mono': mono, 'drawer-field__value--empty': !modelValue }"
    >
      {{ modelValue || placeholder || '—' }}
    </div>

    <div v-if="hint" class="drawer-field__hint">{{ hint }}</div>
  </div>
</template>

<style scoped>
.drawer-field {
  display: flex; flex-direction: column;
  gap: 6px;
}
.drawer-field__label {
  font-size: 10px; font-weight: 500;
  letter-spacing: .16em;
  text-transform: uppercase;
  color: var(--text-4);
  font-family: 'JetBrains Mono', monospace;
}
.drawer-field__input {
  padding: 9px 12px;
  font-size: 13px;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  font-family: inherit;
  outline: none;
  transition: border-color .15s, box-shadow .15s;
}
.drawer-field__input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--ring);
}
.drawer-field__input--mono { font-family: 'JetBrains Mono', monospace; }

.drawer-field__value {
  font-size: 13px;
  color: var(--text);
  min-height: 18px;
  padding: 2px 0;
  word-break: break-word;
}
.drawer-field__value--mono { font-family: 'JetBrains Mono', monospace; }
.drawer-field__value--empty { color: var(--placeholder); }

.drawer-field__hint {
  font-size: 11px;
  color: var(--text-4);
}
</style>
