<script setup lang="ts">
import { ref, computed, onMounted, onUpdated, nextTick } from 'vue'
import { usePortal } from './composables/usePortal'
import { api } from './api'
import ChannelsView from './pages/ChannelsView.vue'
import GroupsView from './pages/GroupsView.vue'
import RulesView from './pages/RulesView.vue'
import JournalView from './pages/JournalView.vue'

declare const feather: any

const { loaded, load, canView } = usePortal()
type TabKey = 'channels' | 'groups' | 'rules' | 'journal'
const activeTab = ref<TabKey>('channels')

// Counts per tab (updated by views). Используются как `t.count` в PageHeader.
const counts = ref<Record<TabKey, number | null>>({
  channels: null, groups: null, rules: null, journal: null,
})

const tabs = computed(() => [
  { id: 'channels', label: 'Каналы',  count: counts.value.channels ?? undefined },
  { id: 'groups',   label: 'Группы',  count: counts.value.groups   ?? undefined },
  { id: 'rules',    label: 'Правила', count: counts.value.rules    ?? undefined },
  { id: 'journal',  label: 'Журнал',  count: counts.value.journal  ?? undefined },
])

function updateCount(tab: TabKey, n: number) { counts.value[tab] = n }
function switchTab(id: string) { activeTab.value = id as TabKey }

const activeView = computed(() => ({
  channels: ChannelsView, groups: GroupsView, rules: RulesView, journal: JournalView,
}[activeTab.value]))

onMounted(async () => {
  await load()
  nextTick(() => feather?.replace())
})
onUpdated(() => { nextTick(() => feather?.replace()) })
</script>

<template>
  <div v-if="!loaded" class="mod-loading">Загрузка…</div>
  <div v-else-if="!canView()" class="mod-denied">Доступ запрещён</div>
  <component
    v-else
    :is="activeView"
    :tabs="tabs"
    :active-tab="activeTab"
    @switch-tab="switchTab"
    @count="(n: number) => updateCount(activeTab, n)"
  />
</template>

<style scoped>
.mod-loading, .mod-denied {
  padding: 80px 32px;
  text-align: center;
  color: var(--text-4);
  font-size: 14px;
}
</style>
