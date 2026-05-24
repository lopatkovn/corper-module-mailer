<script setup lang="ts">
import { ref, computed, watch, onMounted, onUpdated, nextTick } from 'vue'
import { api } from '../api'
import DrawerSection from '../components/DrawerSection.vue'
import DrawerField from '../components/DrawerField.vue'
import GhostBtn from '../components/GhostBtn.vue'
import PrimaryBtn from '../components/PrimaryBtn.vue'

declare const feather: any

interface ChannelFull {
  id?: number
  kind: string
  is_enabled: boolean
  label: string
  config: any
  last_test_at: string | null
  last_test_ok: boolean | null
  last_test_error: string | null
}

const props = defineProps<{
  channel: ChannelFull
  canManage: boolean
}>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'updated'): void
}>()

const editing = ref(false)
const saving = ref(false)
const draft = ref<ChannelFull>({ ...props.channel, config: { ...(props.channel.config || {}) } })

// Drafts для секретов — пишутся, только если непустые
const newPassword = ref('')
const newBotToken = ref('')

// Test email modal
const testModal = ref(false)
const testTo = ref('')
const testSending = ref(false)
const testResult = ref<string | null>(null)

// Bot check
const botChecking = ref(false)
const botCheckResult = ref<string | null>(null)

watch(() => props.channel, (c) => {
  draft.value = { ...c, config: { ...(c.config || {}) } }
  editing.value = false
  newPassword.value = ''
  newBotToken.value = ''
  testResult.value = null
  botCheckResult.value = null
}, { immediate: true })

onMounted(() => nextTick(() => feather?.replace()))
onUpdated(() => nextTick(() => feather?.replace()))

const isEmail = computed(() => props.channel.kind === 'email')

const eyebrow = computed(() => isEmail.value ? 'EMAIL · SMTP' : 'TELEGRAM · BOT')
const headerTitle = computed(() => draft.value.label || (isEmail.value ? 'SMTP-канал' : 'Telegram-бот'))

const statusBadge = computed(() => {
  const c = props.channel
  if (!c.is_enabled) return { variant: 'status-former', label: 'не настроен' }
  if (c.last_test_ok === true) return { variant: 'status-active', label: 'готов' }
  if (c.last_test_ok === false) return { variant: 'status-error', label: 'ошибка' }
  return { variant: 'role', label: 'не проверен' }
})

function startEdit() {
  if (!props.canManage) return
  editing.value = true
  newPassword.value = ''
  newBotToken.value = ''
}
function cancelEdit() {
  draft.value = { ...props.channel, config: { ...(props.channel.config || {}) } }
  newPassword.value = ''
  newBotToken.value = ''
  editing.value = false
}
async function save() {
  saving.value = true
  try {
    const cfg: any = { ...(draft.value.config || {}) }
    // Очистка нечитаемых ключей маски
    delete cfg.has_password
    delete cfg.has_bot_token
    if (isEmail.value && newPassword.value) cfg.password = newPassword.value
    if (!isEmail.value && newBotToken.value) cfg.bot_token = newBotToken.value
    // Автовключение канала, когда есть достаточный конфиг — пользователь
    // не выбирает is_enabled явно (нет toggle'а), активным считается «настроенным».
    const sufficient = isEmail.value
      ? !!(cfg.host && cfg.username && (newPassword.value || draft.value.config?.has_password))
      : !!(newBotToken.value || draft.value.config?.has_bot_token)
    // Дефолтный label по виду канала, если пользователь не задавал
    const label = (draft.value.label || '').trim() ||
      (isEmail.value ? 'SMTP компании' : 'Бот компании')
    const url = isEmail.value ? '/api/mailer/channels/email' : '/api/mailer/channels/telegram'
    await api.put(url, {
      is_enabled: sufficient,
      label,
      config: cfg,
    })
    editing.value = false
    emit('updated')
  } finally { saving.value = false }
}

function openTest() {
  testTo.value = ''
  testResult.value = null
  testModal.value = true
}
async function sendTest() {
  if (!testTo.value.includes('@')) return
  testSending.value = true
  try {
    const res = await api.post('/api/mailer/channels/email/test', { to: testTo.value }).then(r => r.data)
    testResult.value = `Принято в очередь (id=${res.message_id}). Worker отправит в течение 5 секунд.`
    setTimeout(() => emit('updated'), 5000)
  } catch (e: any) {
    testResult.value = 'Ошибка: ' + (e?.response?.data?.error || e?.message || e)
  } finally { testSending.value = false }
}

async function checkBot() {
  botChecking.value = true
  botCheckResult.value = null
  try {
    const res = await api.post('/api/mailer/bot/check', {}).then(r => r.data)
    if (res.ok) {
      botCheckResult.value = `OK · @${res.bot_username} · id=${res.bot_id}`
      emit('updated')
    } else {
      botCheckResult.value = 'Ошибка: ' + (res.error || 'неизвестно')
    }
  } catch (e: any) {
    botCheckResult.value = 'Ошибка: ' + (e?.response?.data?.error || e?.message || e)
  } finally { botChecking.value = false }
}

// ── Bot branding ─────────────────────────────────────────────────────────
interface BrandingCommand { command: string; description: string }
const branding = ref({ name: '', description: '', short_description: '', commands_text: '' })
const brandingLoaded = ref(false)
const brandingLoading = ref(false)
const brandingSaving = ref(false)
const brandingResult = ref<string | null>(null)

function _commandsToText(cmds: BrandingCommand[]): string {
  return (cmds || []).map(c => `${c.command}: ${c.description}`).join('\n')
}
function _textToCommands(text: string): BrandingCommand[] {
  const out: BrandingCommand[] = []
  for (const line of (text || '').split('\n')) {
    const t = line.trim()
    if (!t) continue
    const idx = t.indexOf(':')
    if (idx < 1) continue
    const cmd = t.slice(0, idx).trim().replace(/^\//, '')
    const desc = t.slice(idx + 1).trim()
    if (cmd && desc) out.push({ command: cmd, description: desc })
  }
  return out
}

async function loadBranding() {
  if (brandingLoaded.value) return
  brandingLoading.value = true
  try {
    const d = await api.get('/api/mailer/bot/branding').then(r => r.data)
    branding.value = {
      name: d.name || '',
      description: d.description || '',
      short_description: d.short_description || '',
      commands_text: _commandsToText(d.commands || []),
    }
    brandingLoaded.value = true
  } catch (e: any) {
    brandingResult.value = 'Не удалось загрузить: ' + (e?.response?.data?.error || e?.message || e)
  } finally { brandingLoading.value = false }
}

async function saveBranding() {
  brandingSaving.value = true
  brandingResult.value = null
  try {
    const body = {
      name: branding.value.name,
      description: branding.value.description,
      short_description: branding.value.short_description,
      commands: _textToCommands(branding.value.commands_text),
    }
    const res = await api.put('/api/mailer/bot/branding', body).then(r => r.data)
    if (res.ok) {
      brandingResult.value = `Применено: ${(res.applied || []).join(', ')}`
    } else {
      brandingResult.value = `Частично: ${(res.applied || []).join(', ')}; ошибки: ${(res.errors || []).join('; ')}`
    }
  } catch (e: any) {
    brandingResult.value = 'Ошибка: ' + (e?.response?.data?.error || e?.message || e)
  } finally { brandingSaving.value = false }
}

function fmtDate(d: string | null): string {
  return d ? new Date(d).toLocaleString('ru-RU') : '—'
}
</script>

<template>
  <aside class="dp">
    <!-- Header -->
    <div class="dp__header">
      <div class="dp__header-top">
        <span class="dp__eyebrow">{{ eyebrow }}</span>
        <div class="dp__header-actions">
          <button v-if="canManage && !editing" class="dp__icon-btn" title="Редактировать" @click="startEdit">
            <i data-feather="edit-2"></i>
          </button>
          <button class="dp__icon-btn" title="Закрыть (Esc)" @click="emit('close')">
            <i data-feather="x"></i>
          </button>
        </div>
      </div>
      <h2 class="dp__title">{{ headerTitle }}</h2>
      <div class="dp__badges">
        <span :class="['badge', `badge--${statusBadge.variant}`]">{{ statusBadge.label }}</span>
        <span class="badge badge--neutral">{{ isEmail ? 'SMTP' : 'Telegram Bot API' }}</span>
      </div>
    </div>

    <!-- Body -->
    <div class="dp__body">
      <!-- Last test info -->
      <DrawerSection title="Последняя проверка">
        <div class="dp__last">
          <div class="dp__last-row">
            <span>Когда</span>
            <span :class="['dp__last-val', { 'dp__last-val--empty': !channel.last_test_at }]">
              {{ fmtDate(channel.last_test_at) }}
            </span>
          </div>
          <div class="dp__last-row">
            <span>Результат</span>
            <span :class="['dp__last-val', channel.last_test_ok === true ? 'dp__last-val--ok'
                                       : channel.last_test_ok === false ? 'dp__last-val--err'
                                       : 'dp__last-val--empty']">
              {{ channel.last_test_ok === true ? 'OK'
               : channel.last_test_ok === false ? 'Ошибка' : 'не проверялся' }}
            </span>
          </div>
          <div v-if="channel.last_test_error" class="dp__last-err">{{ channel.last_test_error }}</div>
        </div>
      </DrawerSection>

      <!-- EMAIL specifics -->
      <template v-if="isEmail">
        <DrawerSection title="SMTP сервер">
          <DrawerField label="Хост" v-model="draft.config.host" :editing="editing"
                       placeholder="smtp.example.com" mono />
          <DrawerField label="Порт" v-model="draft.config.port" :editing="editing"
                       type="number" mono placeholder="587" />
          <div class="dp__check">
            <label class="dp__check-label">
              <input type="checkbox" v-model="draft.config.use_tls" :disabled="!editing" />
              <span>STARTTLS (рекомендуется)</span>
            </label>
          </div>
        </DrawerSection>

        <DrawerSection title="Учётные данные">
          <DrawerField label="Логин" v-model="draft.config.username" :editing="editing"
                       placeholder="noreply@example.com" mono />
          <div class="drawer-field">
            <label class="drawer-field__label">Пароль</label>
            <template v-if="editing">
              <input class="drawer-field__input drawer-field__input--mono"
                     type="password"
                     v-model="newPassword"
                     :placeholder="draft.config.has_password ? '••••••• сохранён — оставьте пустым' : 'введите пароль'" />
              <div class="drawer-field__hint">Введите новое значение, чтобы изменить. Пустое поле = «не менять».</div>
            </template>
            <div v-else class="drawer-field__value drawer-field__value--mono"
                 :class="{ 'drawer-field__value--empty': !draft.config.has_password }">
              {{ draft.config.has_password ? '••••••• (сохранён)' : 'не задан' }}
            </div>
          </div>
        </DrawerSection>

        <DrawerSection title="Отправитель">
          <DrawerField label="Имя" v-model="draft.config.sender_name" :editing="editing"
                       placeholder="CORPER" />
          <DrawerField label="Email" v-model="draft.config.sender_email" :editing="editing"
                       type="email" placeholder="noreply@example.com" mono />
        </DrawerSection>
      </template>

      <!-- TELEGRAM specifics -->
      <template v-else>
        <DrawerSection title="Бот от @BotFather">
          <div class="drawer-field">
            <label class="drawer-field__label">Токен бота</label>
            <template v-if="editing">
              <input class="drawer-field__input drawer-field__input--mono"
                     type="password"
                     v-model="newBotToken"
                     :placeholder="draft.config.has_bot_token ? '••••••• сохранён — оставьте пустым' : '123456:ABC…'" />
              <div class="drawer-field__hint">Получите токен у @BotFather через /newbot.</div>
            </template>
            <div v-else class="drawer-field__value drawer-field__value--mono"
                 :class="{ 'drawer-field__value--empty': !draft.config.has_bot_token }">
              {{ draft.config.has_bot_token ? '••••••• (сохранён)' : 'не задан' }}
            </div>
          </div>
        </DrawerSection>

        <DrawerSection title="Информация о боте">
          <template #action>
            <button v-if="canManage && draft.config.has_bot_token && !editing"
                    class="dp__inline-btn" :disabled="botChecking" @click="checkBot">
              <i data-feather="check-circle"></i>
              <span>{{ botChecking ? 'Проверяю…' : 'Проверить' }}</span>
            </button>
          </template>
          <DrawerField label="@username" :model-value="draft.config.bot_username" :editing="false"
                       placeholder="заполнится после «Проверить»" mono />
          <DrawerField label="bot_id" :model-value="draft.config.bot_id" :editing="false"
                       placeholder="заполнится после «Проверить»" mono />
          <div v-if="botCheckResult" class="dp__inline-result">{{ botCheckResult }}</div>
          <div class="drawer-field__hint">
            После проверки добавьте бота в Telegram-чат (как админ с правом писать) — чат появится
            на вкладке «Группы» автоматически.
          </div>
        </DrawerSection>

        <!-- Бот-брендинг — only for telegram, после bot/check -->
        <DrawerSection v-if="canManage && draft.config.has_bot_token && !editing"
                       title="Брендинг бота">
          <template #action>
            <button class="dp__inline-btn" :disabled="brandingLoading" @click="loadBranding">
              <i :data-feather="brandingLoaded ? 'refresh-cw' : 'download'"></i>
              <span>{{ brandingLoading ? 'Загружаю…' : (brandingLoaded ? 'Перечитать' : 'Подтянуть текущие') }}</span>
            </button>
          </template>

          <template v-if="!brandingLoaded">
            <div class="drawer-field__hint">
              Нажмите «Подтянуть текущие», чтобы получить от Telegram имя/описание/команды
              бота — отредактируете и отправите назад одной кнопкой.
            </div>
            <p v-if="brandingResult" class="dp__inline-result">{{ brandingResult }}</p>
          </template>

          <template v-else>
            <div class="drawer-field">
              <label class="drawer-field__label">Имя бота (setMyName, ≤64)</label>
              <input class="drawer-field__input" v-model="branding.name" maxlength="64" />
            </div>
            <div class="drawer-field">
              <label class="drawer-field__label">Короткое описание (setMyShortDescription, ≤120)</label>
              <input class="drawer-field__input" v-model="branding.short_description" maxlength="120" />
              <div class="drawer-field__hint">Показывается в карточке бота в Telegram.</div>
            </div>
            <div class="drawer-field">
              <label class="drawer-field__label">Описание (setMyDescription, ≤512)</label>
              <textarea class="drawer-field__input" v-model="branding.description" rows="3" maxlength="512"></textarea>
              <div class="drawer-field__hint">Видно на экране /start у пользователя.</div>
            </div>
            <div class="drawer-field">
              <label class="drawer-field__label">Команды (setMyCommands)</label>
              <textarea class="drawer-field__input drawer-field__input--mono" v-model="branding.commands_text" rows="4"
                        placeholder="start: Запустить бота
status: Статус подключения
help: Справка"></textarea>
              <div class="drawer-field__hint">
                По одной команде на строку, формат <code>команда: описание</code>.
                Слэш в начале не нужен. Очистка списка = пустое поле.
              </div>
            </div>
            <div class="drawer-field__hint">
              ⚠ Аватарка бота меняется только через @BotFather (Bot API не поддерживает setMyPhoto).
            </div>
            <p v-if="brandingResult" class="dp__inline-result">{{ brandingResult }}</p>
            <div class="dp__footer">
              <button class="dp__primary" :disabled="brandingSaving" @click="saveBranding">
                <i data-feather="send"></i>
                {{ brandingSaving ? 'Отправляю…' : 'Применить в Telegram' }}
              </button>
            </div>
          </template>
        </DrawerSection>
      </template>

      <!-- Footer (editing) -->
      <div v-if="editing" class="dp__footer">
        <GhostBtn @click="cancelEdit" :disabled="saving">Отмена</GhostBtn>
        <PrimaryBtn @click="save" :disabled="saving">
          <template #icon><i data-feather="check"></i></template>
          {{ saving ? 'Сохраняю…' : 'Сохранить' }}
        </PrimaryBtn>
      </div>

      <!-- Quick action: send test email (только для email) -->
      <DrawerSection v-if="isEmail && canManage && !editing" title="Тест отправки">
        <GhostBtn @click="openTest" :disabled="!channel.is_enabled || !draft.config.has_password">
          <i data-feather="send"></i>
          Отправить тестовое письмо
        </GhostBtn>
        <div v-if="!channel.is_enabled" class="drawer-field__hint">Сначала включите канал.</div>
        <div v-else-if="!draft.config.has_password" class="drawer-field__hint">Сначала задайте SMTP-пароль.</div>
      </DrawerSection>
    </div>

    <!-- Test email modal -->
    <div v-if="testModal" class="dp__modal-bg" @click.self="testModal = false">
      <div class="dp__modal">
        <h3 class="dp__modal-title">Тестовое письмо</h3>
        <label class="drawer-field__label">Кому</label>
        <input class="drawer-field__input" type="email" v-model="testTo" placeholder="you@example.com" />
        <div v-if="testResult" class="dp__modal-result">{{ testResult }}</div>
        <div class="dp__modal-actions">
          <GhostBtn @click="testModal = false">{{ testResult ? 'Закрыть' : 'Отмена' }}</GhostBtn>
          <PrimaryBtn v-if="!testResult" @click="sendTest" :disabled="testSending || !testTo.includes('@')">
            <template #icon><i data-feather="send"></i></template>
            {{ testSending ? 'Отправляю…' : 'Отправить' }}
          </PrimaryBtn>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.dp {
  width: 420px;
  flex-shrink: 0;
  background: var(--bg);
  border-left: 1px solid var(--border);
  display: flex; flex-direction: column;
  align-self: stretch;
  overflow: auto;
  font-size: 13px;
}

.dp__header {
  padding: 18px 22px 14px;
  border-bottom: 1px solid var(--border-2);
  display: flex; flex-direction: column; gap: 10px;
  flex-shrink: 0;
}
.dp__header-top { display: flex; justify-content: space-between; align-items: center; }
.dp__eyebrow {
  font-size: 10px; letter-spacing: .16em; text-transform: uppercase;
  color: var(--text-4); font-family: 'JetBrains Mono', monospace;
}
.dp__header-actions { display: flex; gap: 4px; }
.dp__icon-btn {
  width: 30px; height: 30px; border: 0; border-radius: 7px;
  background: transparent; color: var(--text-2); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: background .15s, color .15s;
}
.dp__icon-btn:hover { background: var(--panel); color: var(--text); }
.dp__icon-btn :deep(svg) { width: 15px; height: 15px; }

.dp__title {
  font-size: 22px; font-weight: 600; letter-spacing: -0.02em;
  margin: 0; color: var(--text); word-break: break-word;
}
.dp__badges { display: flex; gap: 6px; flex-wrap: wrap; }

.dp__body {
  flex: 1; overflow-y: auto;
  padding: 18px 22px 24px;
  display: flex; flex-direction: column; gap: 22px;
}

.dp__last {
  background: var(--surface);
  border: 1px solid var(--border-2);
  border-radius: 9px;
  padding: 10px 12px;
  display: flex; flex-direction: column; gap: 4px;
  font-size: 12px;
}
.dp__last-row { display: flex; justify-content: space-between; align-items: baseline; }
.dp__last-row > span:first-child { color: var(--text-3); }
.dp__last-val { font-family: 'JetBrains Mono', monospace; color: var(--text); }
.dp__last-val--empty { color: var(--placeholder); }
.dp__last-val--ok { color: var(--status-active-fg); }
.dp__last-val--err { color: var(--danger); }
.dp__last-err {
  margin-top: 6px; padding: 6px 8px;
  background: #fbe8e7; border: 1px solid #f3c5c2; border-radius: 6px;
  color: #b3261e; font-size: 11px; line-height: 1.4;
  font-family: 'JetBrains Mono', monospace;
}

.dp__check { padding: 4px 0; }
.dp__check-label {
  display: flex; align-items: center; gap: 8px;
  font-size: 12px; color: var(--text-2); line-height: 1.4;
  cursor: pointer;
}
.dp__check-label input { accent-color: var(--accent); }

.dp__inline-btn {
  border: 0; background: transparent; color: var(--accent);
  font-size: 12px; cursor: pointer; padding: 2px 6px;
  display: inline-flex; align-items: center; gap: 4px;
  font-family: inherit;
}
.dp__inline-btn:disabled { opacity: .55; cursor: not-allowed; }
.dp__inline-btn:hover:not(:disabled) { text-decoration: underline; }
.dp__inline-btn :deep(svg) { width: 12px; height: 12px; }

.dp__inline-result {
  margin-top: -4px; padding: 8px 10px;
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 7px; font-size: 12px; color: var(--text-2);
}

.dp__footer {
  display: flex; gap: 8px; justify-content: flex-end;
  padding-top: 8px;
  border-top: 1px solid var(--border-2);
}

/* Modal */
.dp__modal-bg {
  position: fixed; inset: 0; background: rgba(0,0,0,.35);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.dp__modal {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 20px; min-width: 380px; max-width: 460px;
  box-shadow: 0 10px 40px rgba(0,0,0,.16);
}
.dp__modal-title { margin: 0 0 14px; font-size: 16px; font-weight: 600; color: var(--text); }
.dp__modal-result {
  margin-top: 12px; padding: 10px 12px;
  background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
  font-size: 12px; color: var(--text);
}
.dp__modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 14px; }

/* Локальный badge */
.badge {
  display: inline-flex; align-items: center;
  font-size: 11px; font-weight: 500;
  padding: 3px 8px;
  border-radius: 5px;
  white-space: nowrap;
}
.badge--status-active { background: var(--status-active-bg); color: var(--status-active-fg); }
.badge--status-former { background: var(--panel); color: var(--text-3); }
.badge--role          { background: var(--role-bg); color: var(--role-fg); }
.badge--neutral       { background: var(--panel); color: var(--text-2); }
.badge--status-error  { background: #fbe8e7; color: #b3261e; }

/* DrawerField inline overrides (одинаковые с shell) */
.drawer-field { display: flex; flex-direction: column; gap: 6px; }
.drawer-field__label {
  font-size: 10px; font-weight: 500;
  letter-spacing: .16em; text-transform: uppercase;
  color: var(--text-4); font-family: 'JetBrains Mono', monospace;
}
.drawer-field__input {
  padding: 9px 12px; font-size: 13px;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background: var(--surface); color: var(--text);
  font-family: inherit; outline: none;
  transition: border-color .15s, box-shadow .15s;
}
.drawer-field__input:focus {
  border-color: var(--accent); box-shadow: 0 0 0 3px var(--ring);
}
.drawer-field__input--mono { font-family: 'JetBrains Mono', monospace; }
.drawer-field__value {
  font-size: 13px; color: var(--text);
  min-height: 18px; padding: 2px 0; word-break: break-word;
}
.drawer-field__value--mono { font-family: 'JetBrains Mono', monospace; }
.drawer-field__value--empty { color: var(--placeholder); }
.drawer-field__hint { font-size: 11px; color: var(--text-4); }
</style>
