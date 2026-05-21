export const config = {
  portalUrl: import.meta.env.VITE_PORTAL_URL || '',
  moduleName: import.meta.env.VITE_MODULE_NAME || 'mailer',
  moduleSection: import.meta.env.VITE_MODULE_SECTION || 'notifications',
  basePath: import.meta.env.BASE_URL || '/',
}
