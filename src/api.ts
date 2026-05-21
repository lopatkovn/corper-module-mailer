import axios from 'axios'
import { config } from './config'

export const api = axios.create({
  baseURL: import.meta.env.DEV ? '' : config.portalUrl,
  withCredentials: true,
})

api.interceptors.request.use((req) => {
  const cid = localStorage.getItem('activeCompanyId') || ''
  if (cid) {
    req.params = { ...req.params, company_id: cid }
  }
  return req
})
