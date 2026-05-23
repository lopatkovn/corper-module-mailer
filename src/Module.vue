<script setup lang="ts">
import { ref, onMounted, onUpdated, nextTick } from 'vue'
import { usePortal } from './composables/usePortal'
import ChannelsPage from './pages/ChannelsPage.vue'
import GroupsPage from './pages/GroupsPage.vue'
import RulesPage from './pages/RulesPage.vue'
import JournalPage from './pages/JournalPage.vue'

declare const feather: any

const { loaded, load, canView } = usePortal()
type TabKey = 'channels' | 'groups' | 'rules' | 'journal'
const activeTab = ref<TabKey>('channels')

const tabs: { key: TabKey; label: string }[] = [
  { key: 'channels', label: 'Каналы' },
  { key: 'groups',   label: 'Группы' },
  { key: 'rules',    label: 'Правила' },
  { key: 'journal',  label: 'Журнал' },
]

onMounted(async () => {
  await load()
  nextTick(() => feather?.replace())
})
onUpdated(() => { nextTick(() => feather?.replace()) })
</script>

<template>
  <div class="mod">
    <div v-if="!loaded" class="mod-loading">Загрузка…</div>
    <div v-else-if="!canView()" class="mod-denied">Доступ запрещён</div>
    <template v-else>
      <nav class="mod__tabs">
        <button v-for="t in tabs" :key="t.key"
                :class="['mod__tab', { 'mod__tab--active': activeTab === t.key }]"
                @click="activeTab = t.key">{{ t.label }}</button>
      </nav>
      <div class="mod__content">
        <ChannelsPage v-if="activeTab === 'channels'" />
        <GroupsPage   v-else-if="activeTab === 'groups'" />
        <RulesPage    v-else-if="activeTab === 'rules'" />
        <JournalPage  v-else-if="activeTab === 'journal'" />
      </div>
    </template>
  </div>
</template>

<style scoped>
.mod { padding: 0 24px 40px; max-width: 1280px; margin: 0 auto; }
.mod__tabs {
  display: flex; gap: 4px; padding: 3px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  margin: 18px 0 18px;
  width: max-content;
}
.mod__tab {
  padding: 8px 18px;
  border: 0; border-radius: 8px;
  background: transparent; color: var(--text-3);
  cursor: pointer; font-size: 13px; font-weight: 500;
  transition: background .12s, color .12s;
  font-family: inherit;
}
.mod__tab:hover { color: var(--text); }
.mod__tab--active {
  background: var(--surface); color: var(--text);
  box-shadow: 0 1px 3px rgba(0,0,0,.06);
}
.mod-loading, .mod-denied {
  padding: 60px 0; text-align: center; color: var(--text-3);
}
</style>
