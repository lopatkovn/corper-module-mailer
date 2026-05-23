import { ref } from 'vue'
import { config } from '../config'
import type { PortalUser, Company, Branch, Employee } from '../types'

const user = ref<PortalUser | null>(null)
const company = ref<Company | null>(null)
const branches = ref<Branch[]>([])
const companies = ref<Company[]>([])
const employees = ref<Employee[]>([])
const companyId = ref('')
const loaded = ref(false)

/**
 * Единая точка доступа к данным портала.
 *
 * Использование:
 *   const { user, company, branches, companyId, loaded, load, canView, canManage } = usePortal()
 *   onMounted(() => load())
 */
export function usePortal() {
  async function load() {
    // Определяем активную компанию: URL param > localStorage > /api/me fallback
    const url = new URL(window.location.href)
    companyId.value = url.searchParams.get('company_id')
      || localStorage.getItem('activeCompanyId')
      || ''

    const base = config.portalUrl
    const opts: RequestInit = { credentials: 'include' }

    const [meRes, coRes, brRes] = await Promise.all([
      fetch(`${base}/api/me`, opts).then(r => r.ok ? r.json() : null).catch(() => null),
      companyId.value
        ? fetch(`${base}/companies/${companyId.value}`, opts).then(r => r.ok ? r.json() : null).catch(() => null)
        : Promise.resolve(null),
      companyId.value
        ? fetch(`${base}/companies/${companyId.value}/branches`, opts).then(r => r.ok ? r.json() : []).catch(() => [])
        : Promise.resolve([]),
    ])

    user.value = meRes
    company.value = coRes
    branches.value = brRes || []

    if (!companyId.value && meRes?.company_id) {
      companyId.value = String(meRes.company_id)
    }

    loaded.value = true

    if (import.meta.env.DEV) {
      await loadCompanies()
      await loadEmployees()
    }
  }

  /** Загружает все доступные компании пользователя (dev-only) */
  async function loadCompanies() {
    if (!user.value?.company_ids?.length) return
    const base = config.portalUrl
    const opts: RequestInit = { credentials: 'include' }
    const results = await Promise.all(
      user.value.company_ids.map(id =>
        fetch(`${base}/companies/${id}`, opts).then(r => r.ok ? r.json() : null).catch(() => null)
      )
    )
    companies.value = results.filter(Boolean)
  }

  /** Загружает сотрудников активной компании (dev-only) */
  async function loadEmployees() {
    if (!companyId.value) return
    const base = config.portalUrl
    const opts: RequestInit = { credentials: 'include' }
    const res = await fetch(`${base}/api/employees?company_id=${companyId.value}`, opts).catch(() => null)
    employees.value = res && res.ok ? await res.json() : []
  }

  /** Переключает активную компанию (имитирует shell) */
  async function switchCompany(id: number) {
    companyId.value = String(id)
    localStorage.setItem('activeCompanyId', String(id))
    await load()
    window.postMessage({ type: 'company-changed', companyId: id }, '*')
  }

  /** Имеет ли пользователь доступ к просмотру модуля */
  function canView(section?: string): boolean {
    if (!user.value) return false
    if (['admin', 'super_admin'].includes(user.value.portal_role)) return true
    const sec = section || config.moduleSection
    return !!user.value.permissions?.[sec]?.view
  }

  /** Может ли пользователь редактировать (добавлять/удалять) */
  function canManage(section?: string): boolean {
    if (!user.value) return false
    if (['admin', 'super_admin'].includes(user.value.portal_role)) return true
    const sec = section || config.moduleSection
    return !!user.value.permissions?.[sec]?.manage
  }

  // Слушаем events от parent shell (когда модуль в iframe)
  window.addEventListener('message', (e) => {
    if (e.data?.type === 'company-changed') {
      companyId.value = String(e.data.companyId)
      load()
    } else if (e.data?.type === 'theme-changed') {
      applyThemeFromPayload(e.data)
    }
  })

  // На mount применяем сохранённую тему из localStorage (shell кладёт её
  // туда же). Это работает и в standalone (нет shell), и до прихода
  // первого theme-changed postMessage от RemoteModule.vue.
  applyStoredTheme()

  // Cross-tab sync: если пользователь сменил тему в другой вкладке,
  // localStorage `storage` event прилетит сюда автоматически (same-origin).
  window.addEventListener('storage', (e) => {
    if (e.key && (e.key.startsWith('app_theme:') || e.key === 'app_theme' || e.key.startsWith('app_theme_custom:'))) {
      applyStoredTheme()
    }
  })

  return { user, company, companies, branches, employees, companyId, loaded, load, canView, canManage, switchCompany }
}

// ─── Theme handling ─────────────────────────────────────────────────────
// Модуль слушает тему от shell через postMessage и localStorage. Сам
// модуль ничего не вычисляет — shell присылает либо просто themeId
// (для одной из 6 готовых палитр в /portal-shared/themes.css), либо
// themeId='custom' + полный customVars-снэпшот.

type ThemePayload = {
  themeId: string
  customVars?: Record<string, string>
}

const CUSTOM_STYLE_ID = 'corper-custom-theme'

function applyThemeFromPayload(p: ThemePayload) {
  if (!p?.themeId) return
  document.documentElement.setAttribute('data-theme', p.themeId)
  // Inject/replace custom-palette overrides via a single <style> tag so
  // they persist across re-renders and don't pollute inline styles.
  const existing = document.getElementById(CUSTOM_STYLE_ID)
  if (p.themeId === 'custom' && p.customVars) {
    const css = ':root, [data-theme="custom"] {\n' +
      Object.entries(p.customVars).map(([k, v]) => `  ${k}: ${v};`).join('\n') +
      '\n}\n'
    if (existing) existing.textContent = css
    else {
      const tag = document.createElement('style')
      tag.id = CUSTOM_STYLE_ID
      tag.textContent = css
      document.head.appendChild(tag)
    }
  } else if (existing) {
    existing.remove()
  }
}

function applyStoredTheme() {
  // Same per-company key scheme as shell.
  const cid = localStorage.getItem('activeCompanyId')
  const themeId = (cid && localStorage.getItem(`app_theme:${cid}`))
    || localStorage.getItem('app_theme')
    || 'linen'
  let customVars: Record<string, string> | undefined
  if (themeId === 'custom') {
    const raw = cid ? localStorage.getItem(`app_theme_custom:${cid}`) : null
    if (raw) {
      try {
        // Without shell's derive-helpers in standalone we can't compute the
        // full palette — fall back to bare `data-theme="custom"` so the
        // module at least signals intent. When shell broadcasts via
        // postMessage, full vars arrive immediately.
        JSON.parse(raw)
      } catch { /* ignore malformed */ }
    }
  }
  applyThemeFromPayload({ themeId, customVars })
}
