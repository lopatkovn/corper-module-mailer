<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { usePortal } from '../composables/usePortal'
import { api } from '../api'
import Card from '../components/Card.vue'
import Btn from '../components/Btn.vue'
import StatusBadge from '../components/StatusBadge.vue'

const { canManage } = usePortal()

interface EmailCfg {
  host?: string; port?: number; use_tls?: boolean;
  username?: string; sender_name?: string; sender_email?: string;
  has_password?: boolean; password?: string;
}
interface TgCfg {
  bot_username?: string; bot_id?: number;
  has_bot_token?: boolean; bot_token?: string;
}
interface EmailChannel {
  kind: 'email'; is_enabled: boolean; label: string;
  config: EmailCfg;
  last_test_at: string | null; last_test_ok: boolean | null; last_test_error: string | null;
}
interface TgChannel {
  kind: 'telegram'; is_enabled: boolean; label: string;
  config: TgCfg;
  last_test_at: string | null; last_test_ok: boolean | null; last_test_error: string | null;
}
interface PublicChannel {
  kind: string; is_enabled: boolean; label: string; status: string; last_test_at: string | null;
}

const email = ref<EmailChannel>({
  kind: 'email', is_enabled: false, label: '',
  config: { use_tls: true, port: 587 },
  last_test_at: null, last_test_ok: null, last_test_error: null,
})
const tg = ref<TgChannel>({
  kind: 'telegram', is_enabled: false, label: '',
  config: {},
  last_test_at: null, last_test_ok: null, last_test_error: null,
})
const channelsPublic = ref<PublicChannel[]>([])

const emailNewPassword = ref('')
const tgNewToken = ref('')
const emailSaving = ref(false)
const tgSaving = ref(false)
const tgChecking = ref(false)

const testModalOpen = ref(false)
const testTo = ref('')
const testSending = ref(false)
const testResult = ref<string | null>(null)

const emailStatusForBadge = computed(() => statusFromChannel(email.value))
const tgStatusForBadge = computed(() => statusFromChannel(tg.value))

function statusFromChannel(c: { is_enabled: boolean; last_test_ok: boolean | null }): string {
  if (!c.is_enabled) return 'unconfigured'
  if (c.last_test_ok === true) return 'ok'
  if (c.last_test_ok === false) return 'error'
  return 'untested'
}

async function loadAll() {
  const [er, tr, cr] = await Promise.all([
    api.get('/api/mailer/channels/email').then(r => r.data),
    api.get('/api/mailer/channels/telegram').then(r => r.data),
    api.get('/api/mailer/channels').then(r => r.data),
  ])
  email.value = er
  tg.value = tr
  channelsPublic.value = cr
}

async function saveEmail() {
  emailSaving.value = true
  try {
    const cfg: any = { ...email.value.config }
    delete cfg.has_password
    if (emailNewPassword.value) cfg.password = emailNewPassword.value
    await api.put('/api/mailer/channels/email', {
      is_enabled: email.value.is_enabled,
      label: email.value.label,
      config: cfg,
    })
    emailNewPassword.value = ''
    await loadAll()
  } finally { emailSaving.value = false }
}

async function saveTelegram() {
  tgSaving.value = true
  try {
    const cfg: any = { ...tg.value.config }
    delete cfg.has_bot_token
    if (tgNewToken.value) cfg.bot_token = tgNewToken.value
    await api.put('/api/mailer/channels/telegram', {
      is_enabled: tg.value.is_enabled,
      label: tg.value.label,
      config: cfg,
    })
    tgNewToken.value = ''
    await loadAll()
  } finally { tgSaving.value = false }
}

async function checkBot() {
  tgChecking.value = true
  try {
    const res = await api.post('/api/mailer/bot/check', {}).then(r => r.data)
    if (res.ok) {
      await loadAll()
    } else {
      alert('Ошибка проверки бота: ' + (res.error || 'неизвестно'))
      await loadAll()
    }
  } catch (e: any) {
    alert('Ошибка: ' + (e?.response?.data?.error || e?.message || e))
  } finally { tgChecking.value = false }
}

function openTestEmail() {
  testTo.value = ''
  testResult.value = null
  testModalOpen.value = true
}

async function sendTestEmail() {
  if (!testTo.value || !testTo.value.includes('@')) return
  testSending.value = true
  try {
    const res = await api.post('/api/mailer/channels/email/test', { to: testTo.value }).then(r => r.data)
    testResult.value = `Принято в очередь (id=${res.message_id}). Worker отправит в течение 5 секунд — обновите страницу или проверьте статус карточки.`
    // через 5 сек подгрузим обновлённый статус
    setTimeout(loadAll, 5000)
  } catch (e: any) {
    testResult.value = 'Ошибка: ' + (e?.response?.data?.error || e?.message || e)
  } finally { testSending.value = false }
}

onMounted(loadAll)
</script>

<template>
  <div class="ch">
    <header class="ch__head">
      <h1 class="ch__title">Каналы доставки</h1>
      <p class="ch__hint">Настройте SMTP и/или Telegram-бота — модули-источники
        (например, «Пользователи») увидят канал в списке доступных.</p>
    </header>

    <div class="ch__grid">
      <!-- Email Card -->
      <Card eyebrow="EMAIL" title="SMTP-сервер">
        <template #action><StatusBadge :status="emailStatusForBadge" /></template>
        <form @submit.prevent="saveEmail" class="form" :class="{ 'form--ro': !canManage() }">
          <div class="row row--2">
            <label class="field">
              <span class="field__label">Название канала</span>
              <input v-model="email.label" placeholder="SMTP компании" :disabled="!canManage()" />
            </label>
            <label class="check">
              <input type="checkbox" v-model="email.is_enabled" :disabled="!canManage()" />
              <span>Включён</span>
            </label>
          </div>

          <fieldset class="group">
            <legend>SMTP сервер</legend>
            <div class="row row--3">
              <label class="field">
                <span class="field__label">Хост</span>
                <input v-model="email.config.host" placeholder="smtp.gmail.com" :disabled="!canManage()" />
              </label>
              <label class="field field--narrow">
                <span class="field__label">Порт</span>
                <input v-model.number="email.config.port" type="number" :disabled="!canManage()" />
              </label>
              <label class="check check--inline">
                <input type="checkbox" v-model="email.config.use_tls" :disabled="!canManage()" />
                <span>TLS</span>
              </label>
            </div>
          </fieldset>

          <fieldset class="group">
            <legend>Учётные данные</legend>
            <div class="row row--2">
              <label class="field">
                <span class="field__label">Логин</span>
                <input v-model="email.config.username" :disabled="!canManage()" />
              </label>
              <label class="field">
                <span class="field__label">Пароль {{ email.config.has_password ? '(сохранён)' : '' }}</span>
                <input v-model="emailNewPassword" type="password"
                       :placeholder="email.config.has_password ? '••••••• оставьте пустым' : 'введите пароль'"
                       :disabled="!canManage()" />
              </label>
            </div>
          </fieldset>

          <fieldset class="group">
            <legend>Отправитель</legend>
            <div class="row row--2">
              <label class="field">
                <span class="field__label">Имя</span>
                <input v-model="email.config.sender_name" placeholder="CORPER" :disabled="!canManage()" />
              </label>
              <label class="field">
                <span class="field__label">Email</span>
                <input v-model="email.config.sender_email" type="email" :disabled="!canManage()" />
              </label>
            </div>
          </fieldset>

          <div class="form__meta" v-if="email.last_test_at">
            Последняя проверка: {{ new Date(email.last_test_at).toLocaleString('ru-RU') }}
            <span v-if="email.last_test_ok"> · OK</span>
            <span v-else-if="email.last_test_ok === false" class="form__err"> · {{ email.last_test_error }}</span>
          </div>

          <div class="form__actions">
            <Btn variant="primary" :disabled="emailSaving || !canManage()">
              {{ emailSaving ? 'Сохраняю…' : 'Сохранить' }}
            </Btn>
            <Btn variant="ghost" icon="send" :disabled="!email.is_enabled || !canManage()"
                 @click.prevent="openTestEmail">Отправить тест</Btn>
          </div>
        </form>
      </Card>

      <!-- Telegram Card -->
      <Card eyebrow="TELEGRAM" title="Бот компании">
        <template #action><StatusBadge :status="tgStatusForBadge" /></template>
        <form @submit.prevent="saveTelegram" class="form" :class="{ 'form--ro': !canManage() }">
          <div class="row row--2">
            <label class="field">
              <span class="field__label">Название канала</span>
              <input v-model="tg.label" placeholder="Бот рассылок" :disabled="!canManage()" />
            </label>
            <label class="check">
              <input type="checkbox" v-model="tg.is_enabled" :disabled="!canManage()" />
              <span>Включён</span>
            </label>
          </div>

          <fieldset class="group">
            <legend>Бот от @BotFather</legend>
            <label class="field">
              <span class="field__label">Токен {{ tg.config.has_bot_token ? '(сохранён)' : '' }}</span>
              <input v-model="tgNewToken" type="password"
                     :placeholder="tg.config.has_bot_token ? '••••••• оставьте пустым' : '123456789:ABCdef…'"
                     :disabled="!canManage()" />
            </label>
          </fieldset>

          <fieldset class="group">
            <legend>Информация о боте</legend>
            <div class="row row--2">
              <label class="field">
                <span class="field__label">@username</span>
                <input :value="tg.config.bot_username || ''" readonly placeholder="заполнится после «Проверить»" />
              </label>
              <label class="field field--narrow">
                <span class="field__label">bot_id</span>
                <input :value="tg.config.bot_id || ''" readonly />
              </label>
            </div>
          </fieldset>

          <div class="form__meta" v-if="tg.last_test_at">
            Последняя проверка: {{ new Date(tg.last_test_at).toLocaleString('ru-RU') }}
            <span v-if="tg.last_test_ok"> · OK</span>
            <span v-else-if="tg.last_test_ok === false" class="form__err"> · {{ tg.last_test_error }}</span>
          </div>

          <div class="form__actions">
            <Btn variant="primary" :disabled="tgSaving || !canManage()">
              {{ tgSaving ? 'Сохраняю…' : 'Сохранить' }}
            </Btn>
            <Btn variant="ghost" icon="check-circle"
                 :disabled="!tg.config.has_bot_token || tgChecking || !canManage()"
                 @click.prevent="checkBot">
              {{ tgChecking ? 'Проверяю…' : 'Проверить бота' }}
            </Btn>
          </div>

          <p class="ch__hint ch__hint--small">
            После «Проверить» — добавьте бота в группу/канал, на вкладке
            <strong>Группы</strong> он появится автоматически.
          </p>
        </form>
      </Card>
    </div>

    <!-- Test email modal -->
    <div v-if="testModalOpen" class="modal-overlay" @click.self="testModalOpen = false">
      <div class="modal">
        <h3 class="modal__title">Тестовое письмо</h3>
        <p>Отправить тестовое письмо на адрес:</p>
        <input v-model="testTo" type="email" placeholder="you@example.com" class="modal__input" />
        <p v-if="testResult" class="modal__result">{{ testResult }}</p>
        <div class="modal__actions">
          <Btn variant="ghost" @click="testModalOpen = false">{{ testResult ? 'Закрыть' : 'Отмена' }}</Btn>
          <Btn v-if="!testResult" variant="primary"
               :disabled="testSending || !testTo.includes('@')" @click="sendTestEmail">
            {{ testSending ? 'Отправляю…' : 'Отправить' }}
          </Btn>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ch__head { margin-bottom: 18px; }
.ch__title { font-size: 22px; font-weight: 600; margin: 0 0 6px; color: var(--text); }
.ch__hint { margin: 0; color: var(--text-3); font-size: 13px; line-height: 1.5; max-width: 720px; }
.ch__hint--small { font-size: 12px; margin-top: 12px; }
.ch__grid {
  display: grid; gap: 16px;
  grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
}
.form { display: flex; flex-direction: column; gap: 14px; }
.form--ro input, .form--ro select { opacity: .75; }
.row { display: flex; gap: 12px; flex-wrap: wrap; }
.row--2 > * { flex: 1 1 200px; }
.row--3 > .field { flex: 1 1 160px; }
.row--3 > .field--narrow { flex: 0 0 90px; }
.group {
  border: 1px solid var(--border); border-radius: 9px;
  padding: 12px 14px 14px; margin: 0;
}
.group > legend {
  padding: 0 6px;
  font-size: 10px; letter-spacing: .14em; text-transform: uppercase;
  color: var(--text-4); font-weight: 500;
}
.field { display: flex; flex-direction: column; gap: 4px; }
.field__label { font-size: 11px; color: var(--text-3); font-weight: 500; }
.field input, .field select {
  padding: 8px 11px; font-size: 13px;
  border: 1px solid var(--border); border-radius: 8px;
  background: var(--surface); color: var(--text);
  font-family: inherit; outline: none;
}
.field input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--ring); }
.field input[readonly] { background: var(--panel); color: var(--text-3); }
.check {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; color: var(--text); cursor: pointer;
  padding-top: 18px;
}
.check input { width: 16px; height: 16px; accent-color: var(--accent); }
.check--inline { padding-top: 22px; }
.form__meta { font-size: 12px; color: var(--text-3); }
.form__err { color: var(--danger); }
.form__actions { display: flex; gap: 10px; }

.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.35);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.modal {
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 20px; min-width: 360px; max-width: 480px;
  box-shadow: 0 10px 40px rgba(0,0,0,.16);
}
.modal__title { margin: 0 0 10px; font-size: 16px; font-weight: 600; }
.modal__input {
  width: 100%; padding: 9px 12px; font-size: 13px;
  border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg); color: var(--text); font-family: inherit;
  box-sizing: border-box;
}
.modal__result {
  margin: 12px 0 0; padding: 10px 12px;
  background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
  font-size: 12px; color: var(--text);
}
.modal__actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 14px; }
</style>
