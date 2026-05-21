<script setup lang="ts">
import { ref, computed, onUpdated, nextTick } from 'vue'
import { usePortal } from '../composables/usePortal'
import { config } from '../config'

declare const feather: any

const { user, company, companies, branches, employees, companyId, loaded, load, switchCompany } = usePortal()

const open = ref(localStorage.getItem('devToolbarOpen') === '1')

const loginEmail = ref('')
const loginPassword = ref('')
const loginError = ref('')
const loginLoading = ref(false)

async function doLogin() {
  loginError.value = ''
  loginLoading.value = true
  try {
    const res = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ email: loginEmail.value, password: loginPassword.value }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => null)
      loginError.value = body?.detail || `Ошибка ${res.status}`
      return
    }
    const data = await res.json()
    if (data.token) {
      document.cookie = `corper_token=${data.token}; path=/; max-age=${7 * 86400}; SameSite=Lax`
    }
    if (data.company_id) {
      localStorage.setItem('activeCompanyId', String(data.company_id))
    }
    loginEmail.value = ''
    loginPassword.value = ''
    await load()
  } catch (e: any) {
    loginError.value = e.message || 'Сетевая ошибка'
  } finally {
    loginLoading.value = false
  }
}

async function doLogout() {
  document.cookie = 'corper_token=; path=/; max-age=0'
  localStorage.removeItem('activeCompanyId')
  window.location.reload()
}

function toggle() {
  open.value = !open.value
  localStorage.setItem('devToolbarOpen', open.value ? '1' : '0')
}

async function onCompanyChange(e: Event) {
  const id = Number((e.target as HTMLSelectElement).value)
  if (id) await switchCompany(id)
}

const sectionPerms = computed(() => {
  if (!user.value) return null
  if (['admin', 'super_admin'].includes(user.value.portal_role)) {
    return { view: true, manage: true }
  }
  return user.value.permissions?.[config.moduleSection] || { view: false, manage: false }
})

onUpdated(() => nextTick(() => { try { feather?.replace() } catch {} }))
</script>

<template>
  <div class="dt">
    <button class="dt-toggle" @click="toggle" title="Dev Toolbar">
      <i data-feather="settings" style="width:16px;height:16px;"></i>
    </button>

    <div v-if="open" class="dt-panel">
      <div class="dt-header">
        <span class="dt-badge">DEV</span>
        <span class="dt-title">Portal Context</span>
        <button class="dt-close" @click="toggle">&times;</button>
      </div>

      <template v-if="!user">
        <div class="dt-section">
          <div class="dt-label">Авторизация</div>
          <form @submit.prevent="doLogin" class="dt-login">
            <input v-model="loginEmail" type="email" placeholder="Email" class="dt-input" required />
            <input v-model="loginPassword" type="password" placeholder="Пароль" class="dt-input" required />
            <div v-if="loginError" class="dt-login-error">{{ loginError }}</div>
            <button type="submit" class="dt-login-btn" :disabled="loginLoading">
              {{ loginLoading ? 'Вход...' : 'Войти' }}
            </button>
          </form>
        </div>
      </template>

      <template v-else>
        <div class="dt-section">
          <div class="dt-label">Пользователь</div>
          <div class="dt-value">{{ user.name }} <span class="dt-role">{{ user.portal_role }}</span></div>
          <button class="dt-logout" @click="doLogout">Выйти</button>
        </div>
        <div class="dt-section">
          <div class="dt-label">Компания</div>
          <select class="dt-select" :value="companyId" @change="onCompanyChange" v-if="companies.length">
            <option v-for="c in companies" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
          <div class="dt-value dt-muted" v-else>{{ company?.name || 'Нет данных' }}</div>
        </div>
        <div class="dt-section">
          <div class="dt-label">Филиалы ({{ branches.length }})</div>
          <div class="dt-list" v-if="branches.length">
            <div v-for="b in branches" :key="b.id" class="dt-list-item">
              <span>{{ b.name }}</span>
              <span class="dt-muted" v-if="b.address">{{ b.address }}</span>
            </div>
          </div>
          <div class="dt-muted" v-else>Нет филиалов</div>
        </div>
        <div class="dt-section">
          <div class="dt-label">Сотрудники ({{ employees.length }})</div>
          <div class="dt-list dt-list--scroll" v-if="employees.length">
            <div v-for="e in employees.slice(0, 20)" :key="e.id" class="dt-list-item">
              <span>{{ e.name }}</span>
              <span class="dt-muted">{{ e.portal_role }}{{ e.position ? ' / ' + e.position : '' }}</span>
            </div>
          </div>
          <div class="dt-muted" v-else>Нет сотрудников</div>
        </div>
        <div class="dt-section">
          <div class="dt-label">Права ({{ config.moduleSection }})</div>
          <div class="dt-perms" v-if="sectionPerms">
            <span :class="['dt-perm', sectionPerms.view ? 'dt-perm--ok' : 'dt-perm--no']">view {{ sectionPerms.view ? '\u2713' : '\u2717' }}</span>
            <span :class="['dt-perm', sectionPerms.manage ? 'dt-perm--ok' : 'dt-perm--no']">manage {{ sectionPerms.manage ? '\u2713' : '\u2717' }}</span>
          </div>
          <div class="dt-muted" v-else>Нет данных</div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.dt { position: fixed; bottom: 16px; right: 16px; z-index: 9999; font-family: 'Inter', -apple-system, sans-serif; font-size: 12px; }
.dt-toggle { width: 36px; height: 36px; border-radius: 50%; border: none; background: #1a1a2e; color: #fff; cursor: pointer; display: flex; align-items: center; justify-content: center; box-shadow: 0 2px 8px rgba(0,0,0,0.2); transition: transform 0.15s; position: absolute; bottom: 0; right: 0; }
.dt-toggle:hover { transform: scale(1.1); }
.dt-panel { position: absolute; bottom: 44px; right: 0; width: 280px; background: #1a1a2e; color: #e0e0e0; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.3); overflow: hidden; }
.dt-header { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid rgba(255,255,255,0.08); }
.dt-badge { background: #4338ca; color: #fff; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; }
.dt-title { font-size: 12px; font-weight: 600; flex: 1; }
.dt-close { background: none; border: none; color: #8b8fa3; font-size: 18px; cursor: pointer; padding: 0 2px; line-height: 1; }
.dt-close:hover { color: #fff; }
.dt-section { padding: 8px 12px; border-bottom: 1px solid rgba(255,255,255,0.05); }
.dt-section:last-child { border-bottom: none; }
.dt-label { font-size: 10px; font-weight: 600; color: #8b8fa3; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
.dt-value { font-size: 13px; }
.dt-muted { color: #6b6f80; font-size: 11px; }
.dt-role { display: inline-block; background: rgba(99,102,241,0.2); color: #a5b4fc; font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 4px; margin-left: 6px; }
.dt-select { width: 100%; padding: 6px 8px; background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.12); border-radius: 6px; color: #e0e0e0; font-size: 12px; font-family: inherit; cursor: pointer; outline: none; }
.dt-select:focus { border-color: #4338ca; }
.dt-select option { background: #1a1a2e; color: #e0e0e0; }
.dt-list { display: flex; flex-direction: column; gap: 2px; }
.dt-list--scroll { max-height: 140px; overflow-y: auto; }
.dt-list--scroll::-webkit-scrollbar { width: 4px; }
.dt-list--scroll::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.15); border-radius: 2px; }
.dt-list-item { display: flex; justify-content: space-between; align-items: baseline; padding: 3px 0; gap: 8px; }
.dt-list-item span:first-child { font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dt-perms { display: flex; gap: 8px; }
.dt-perm { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 4px; }
.dt-perm--ok { background: rgba(22,163,74,0.2); color: #4ade80; }
.dt-perm--no { background: rgba(225,29,72,0.15); color: #fb7185; }
.dt-login { display: flex; flex-direction: column; gap: 6px; margin-top: 4px; }
.dt-input { width: 100%; box-sizing: border-box; padding: 7px 10px; background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.12); border-radius: 6px; color: #e0e0e0; font-size: 12px; font-family: inherit; outline: none; }
.dt-input:focus { border-color: #4338ca; }
.dt-input::placeholder { color: #6b6f80; }
.dt-login-btn { padding: 7px 12px; background: #4338ca; color: #fff; border: none; border-radius: 6px; font-size: 12px; font-weight: 600; font-family: inherit; cursor: pointer; }
.dt-login-btn:hover { background: #3730a3; }
.dt-login-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.dt-login-error { color: #fb7185; font-size: 11px; }
.dt-logout { margin-top: 6px; padding: 4px 10px; background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.1); border-radius: 5px; color: #8b8fa3; font-size: 11px; font-family: inherit; cursor: pointer; }
.dt-logout:hover { color: #fb7185; border-color: rgba(251,113,133,0.3); }
</style>
