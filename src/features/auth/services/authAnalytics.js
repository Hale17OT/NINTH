const allowedEvents = new Set([
  'auth_sign_in_started', 'auth_sign_in_completed', 'auth_sign_up_started', 'auth_sign_up_completed',
  'auth_google_started', 'auth_google_completed', 'auth_failed', 'auth_logout',
])

export const trackAuthEvent = (name, detail = {}) => {
  if (!allowedEvents.has(name)) return
  const safeDetail = Object.fromEntries(Object.entries(detail).filter(([key]) => !/password|token|secret|email/i.test(key)))
  window.dispatchEvent(new CustomEvent('ninth:analytics', { detail: { name, ...safeDetail } }))
}
