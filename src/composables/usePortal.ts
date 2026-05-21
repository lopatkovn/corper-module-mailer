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

// В dev-режиме запросы идут через Vite proxy (same-origin), в prod — напрямую на портал
const base = import.meta.env.DEV ? '' : config.portalUrl

export function usePortal() {
  async function load() {
    const url = new URL(window.location.href)
    companyId.value = url.searchParams.get('company_id')
      || localStorage.getItem('activeCompanyId')
      || ''

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

  async function loadCompanies() {
    if (!user.value?.company_ids?.length) return
    const opts: RequestInit = { credentials: 'include' }
    const results = await Promise.all(
      user.value.company_ids.map(id =>
        fetch(`${base}/companies/${id}`, opts).then(r => r.ok ? r.json() : null).catch(() => null)
      )
    )
    companies.value = results.filter(Boolean)
  }

  async function loadEmployees() {
    if (!companyId.value) return
    const opts: RequestInit = { credentials: 'include' }
    const res = await fetch(`${base}/api/employees?company_id=${companyId.value}`, opts).catch(() => null)
    employees.value = res && res.ok ? await res.json() : []
  }

  async function switchCompany(id: number) {
    companyId.value = String(id)
    localStorage.setItem('activeCompanyId', String(id))
    await load()
    window.postMessage({ type: 'company-changed', companyId: id }, '*')
  }

  /**
   * Rich department context — dept + manager + ancestors + descendants
   * + direct_reports + subtree counts (+ optional subtree_employees).
   * One pull, all the structure data you'll typically need around a node.
   * See INTEGRATION.md → /api/companies/{cid}/departments/{did}/full
   */
  async function loadDepartment(deptId: number, includeEmployees = false): Promise<any | null> {
    if (!companyId.value) return null
    const params = new URLSearchParams()
    if (includeEmployees) params.set('include_subtree_employees', '1')
    const url = `${base}/api/companies/${companyId.value}/departments/${deptId}/full`
      + (params.toString() ? `?${params.toString()}` : '')
    const r = await fetch(url, { credentials: 'include' }).catch(() => null)
    return r && r.ok ? await r.json() : null
  }

  function canView(section?: string): boolean {
    if (!user.value) return false
    if (['admin', 'super_admin'].includes(user.value.portal_role)) return true
    const sec = section || config.moduleSection
    return !!user.value.permissions?.[sec]?.view
  }

  function canManage(section?: string): boolean {
    if (!user.value) return false
    if (['admin', 'super_admin'].includes(user.value.portal_role)) return true
    const sec = section || config.moduleSection
    return !!user.value.permissions?.[sec]?.manage
  }

  window.addEventListener('message', (e) => {
    if (e.data?.type === 'company-changed') {
      companyId.value = String(e.data.companyId)
      load()
    }
  })

  return { user, company, companies, branches, employees, companyId, loaded, load, canView, canManage, switchCompany, loadDepartment }
}
