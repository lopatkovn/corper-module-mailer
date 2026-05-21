/** Текущий пользователь портала (GET /api/me) */
export interface PortalUser {
  id: number
  name: string
  email: string
  portal_role: 'super_admin' | 'admin' | 'manager' | 'employee'
  company_id: number
  company_ids: number[]
  permissions: Record<string, { view: boolean; manage: boolean }> | null
}

/** Компания (GET /companies/{id}) */
export interface Company {
  id: number
  name: string
  slug: string
  timezone: string
  phone: string | null
  email: string | null
  website: string | null
}

/** Филиал (GET /companies/{id}/branches) */
export interface Branch {
  id: number
  name: string
  address: string | null
  phone: string | null
  lat: number | null
  lng: number | null
}

/** Сотрудник (GET /api/employees) */
export interface Employee {
  id: number
  name: string
  email: string
  portal_role: string
  department: string | null
  position: string | null
  phone: string | null
  is_active: boolean
  branch_names: string
}
