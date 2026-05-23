<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '../api'

interface Message {
  id: number; channel_id: number | null; source_module: string;
  event_type: string; to_address: string; subject: string | null;
  status: string; attempts: number; last_error: string | null;
  sent_at: string | null; created_at: string;
}
interface Inbound {
  id: number; chat_id: number; from_username: string | null;
  text: string | null; reply_to_message_id: number | null;
  created_at: string;
}

type Sub = 'out' | 'in'
const sub = ref<Sub>('out')

const messages = ref<Message[]>([])
const inbound = ref<Inbound[]>([])
const statusFilter = ref<string>('')
const kindFilter = ref<string>('')
const loading = ref(false)

async function loadMessages() {
  loading.value = true
  try {
    const params: any = { limit: 100 }
    if (statusFilter.value) params.status = statusFilter.value
    if (kindFilter.value) params.kind = kindFilter.value
    const res = await api.get('/api/mailer/messages', { params }).then(r => r.data)
    messages.value = res.items
  } finally { loading.value = false }
}

async function loadInbound() {
  loading.value = true
  try {
    const res = await api.get('/api/mailer/inbound', { params: { limit: 100 } }).then(r => r.data)
    inbound.value = res.items
  } finally { loading.value = false }
}

function statusClass(s: string): string {
  return {
    sent: 'st--sent',
    pending: 'st--pending',
    sending: 'st--pending',
    failed: 'st--failed',
  }[s] || ''
}

function load() {
  if (sub.value === 'out') loadMessages()
  else loadInbound()
}

onMounted(load)
</script>

<template>
  <div class="jr">
    <header class="jr__head">
      <h1 class="jr__title">Журнал сообщений</h1>
      <nav class="jr__subtabs">
        <button :class="['jr__subtab', { 'jr__subtab--active': sub === 'out' }]"
                @click="sub = 'out'; load()">Исходящие</button>
        <button :class="['jr__subtab', { 'jr__subtab--active': sub === 'in' }]"
                @click="sub = 'in'; load()">Входящие</button>
      </nav>
    </header>

    <div v-if="sub === 'out'" class="jr__filters">
      <label class="filter">
        <span>Статус:</span>
        <select v-model="statusFilter" @change="loadMessages">
          <option value="">Все</option>
          <option value="pending">Pending</option>
          <option value="sending">Sending</option>
          <option value="sent">Sent</option>
          <option value="failed">Failed</option>
        </select>
      </label>
      <label class="filter">
        <span>Канал:</span>
        <select v-model="kindFilter" @change="loadMessages">
          <option value="">Любой</option>
          <option value="email">Email</option>
          <option value="telegram">Telegram</option>
        </select>
      </label>
      <button class="filter__refresh" @click="loadMessages">↻ Обновить</button>
    </div>

    <div v-if="loading" class="jr__empty">Загрузка…</div>

    <!-- Outgoing -->
    <table v-else-if="sub === 'out'" class="jr__table">
      <thead>
        <tr>
          <th>Когда</th>
          <th>Источник</th>
          <th>Событие</th>
          <th>Получатель</th>
          <th>Тема</th>
          <th>Статус</th>
          <th class="num">Попыток</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="!messages.length">
          <td colspan="7" class="jr__empty-row">
            Сообщений ещё нет. Они появятся когда сработает правило или отправите тест с вкладки «Каналы».
          </td>
        </tr>
        <tr v-for="m in messages" :key="m.id">
          <td class="when">{{ new Date(m.created_at).toLocaleString('ru-RU') }}</td>
          <td><code>{{ m.source_module }}</code></td>
          <td><code class="event-key">{{ m.event_type }}</code></td>
          <td>{{ m.to_address }}</td>
          <td>{{ m.subject || '—' }}</td>
          <td>
            <span :class="['st', statusClass(m.status)]">{{ m.status }}</span>
            <div v-if="m.last_error" class="st__err" :title="m.last_error">{{ m.last_error.slice(0, 60) }}…</div>
          </td>
          <td class="num">{{ m.attempts }}</td>
        </tr>
      </tbody>
    </table>

    <!-- Incoming -->
    <table v-else class="jr__table">
      <thead>
        <tr>
          <th>Когда</th>
          <th>chat_id</th>
          <th>От</th>
          <th>Текст</th>
          <th>Reply на</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="!inbound.length">
          <td colspan="5" class="jr__empty-row">
            Входящих сообщений нет. Они появятся когда кто-то напишет боту или в группу с ботом.
          </td>
        </tr>
        <tr v-for="i in inbound" :key="i.id">
          <td class="when">{{ new Date(i.created_at).toLocaleString('ru-RU') }}</td>
          <td><code>{{ i.chat_id }}</code></td>
          <td>{{ i.from_username ? '@' + i.from_username : '—' }}</td>
          <td>{{ i.text || '(без текста)' }}</td>
          <td>{{ i.reply_to_message_id ? '#' + i.reply_to_message_id : '—' }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.jr__head { display: flex; align-items: baseline; gap: 20px; margin-bottom: 14px; }
.jr__title { margin: 0; font-size: 22px; font-weight: 600; color: var(--text); }
.jr__subtabs { display: flex; gap: 4px; padding: 3px;
               background: var(--panel); border: 1px solid var(--border); border-radius: 9px; }
.jr__subtab { padding: 6px 14px; border: 0; border-radius: 7px;
              background: transparent; color: var(--text-3); cursor: pointer;
              font-size: 13px; font-weight: 500; font-family: inherit; }
.jr__subtab--active { background: var(--surface); color: var(--text); }
.jr__filters { display: flex; gap: 12px; margin-bottom: 12px; align-items: center; }
.filter { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-3); }
.filter select { padding: 5px 9px; font-size: 12px;
                 border: 1px solid var(--border); border-radius: 7px;
                 background: var(--surface); color: var(--text); font-family: inherit; }
.filter__refresh { margin-left: auto; background: 0; border: 1px solid var(--border);
                   padding: 6px 12px; border-radius: 7px; cursor: pointer;
                   color: var(--text-3); font-size: 12px; font-family: inherit; }
.filter__refresh:hover { background: var(--surface); color: var(--text); }
.jr__empty { padding: 60px 20px; text-align: center;
             background: var(--panel); border: 1px dashed var(--border); border-radius: 12px;
             color: var(--text-3); }
.jr__empty-row { padding: 30px; text-align: center; color: var(--text-3); }
.jr__table {
  width: 100%; border-collapse: collapse; background: var(--surface);
  border: 1px solid var(--border); border-radius: 12px; overflow: hidden;
  font-size: 12px;
}
.jr__table th, .jr__table td {
  padding: 9px 12px; text-align: left; vertical-align: middle;
  border-bottom: 1px solid var(--border);
}
.jr__table th { background: var(--panel); font-weight: 500; font-size: 10px; color: var(--text-3);
                text-transform: uppercase; letter-spacing: .04em; }
.jr__table tbody tr:last-child td { border-bottom: 0; }
.jr__table .num { text-align: right; }
.when { color: var(--text-3); white-space: nowrap; font-size: 11px; }
.event-key { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-3); }
.st { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px;
      border: 1px solid var(--border); background: var(--surface); }
.st--sent { color: #0a7d3e; border-color: #b6e3c2; background: #e7f6ec; }
.st--pending { color: #8a6d10; border-color: #f0e2a3; background: #fcf6dd; }
.st--failed { color: #b3261e; border-color: #f3c5c2; background: #fbe8e7; }
.st__err { margin-top: 3px; font-size: 10px; color: var(--danger); max-width: 240px;
           overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
