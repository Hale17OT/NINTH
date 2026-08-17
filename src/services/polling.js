const TAB_ID = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`
const LEASE_PREFIX = 'ninth:poll-lease:'

const visible = () => typeof document === 'undefined' || document.visibilityState === 'visible'
const resolveValue = value => typeof value === 'function' ? value() : value
const leaseKey = key => `${LEASE_PREFIX}${resolveValue(key)}`

const readLease = key => {
  try { return JSON.parse(localStorage.getItem(key) || 'null') }
  catch { return null }
}

const claimLease = (key, duration) => {
  if (typeof localStorage === 'undefined') return true
  const storageKey = leaseKey(key)
  const now = Date.now()
  const current = readLease(storageKey)
  if (current?.owner !== TAB_ID && Number(current?.expiresAt || 0) > now) return false
  const lease = { owner: TAB_ID, expiresAt: now + Math.max(2_000, duration * 1.5) }
  try {
    localStorage.setItem(storageKey, JSON.stringify(lease))
    return readLease(storageKey)?.owner === TAB_ID
  } catch {
    return true
  }
}

const releaseLease = key => {
  if (typeof localStorage === 'undefined') return
  const storageKey = leaseKey(key)
  try {
    if (readLease(storageKey)?.owner === TAB_ID) localStorage.removeItem(storageKey)
  } catch { /* storage can be disabled without disabling polling */ }
}

/**
 * A visibility-aware recurring task with a cross-tab lease.
 *
 * Every mounted view gets one initial load so it can render. Recurring work is
 * then performed by only one visible tab for a given key. Hiding or closing the
 * leader releases its lease, allowing another visible NINTH tab to take over.
 */
export const createSharedPoller = ({ key, task, interval, immediate = true }) => {
  let timer
  let stopped = true
  let running = false
  let pending = false
  let activeKey

  const milliseconds = () => {
    const value = Number(resolveValue(interval))
    return Number.isFinite(value) && value > 0 ? Math.max(1_000, value) : null
  }

  const clear = () => {
    window.clearTimeout(timer)
    timer = undefined
  }

  const schedule = () => {
    clear()
    const delay = milliseconds()
    if (!stopped && visible() && delay) timer = window.setTimeout(() => execute(), delay)
  }

  const execute = async ({ force = false } = {}) => {
    if (stopped || !visible()) return
    if (running) { pending = pending || force; return }
    const nextKey = resolveValue(key)
    if (activeKey && activeKey !== nextKey) releaseLease(activeKey)
    activeKey = nextKey
    const delay = milliseconds()
    if (!force && delay && !claimLease(activeKey, delay)) { schedule(); return }
    running = true
    try {
      await task()
      const nextDelay = milliseconds()
      if (!stopped && visible() && nextDelay) claimLease(activeKey, nextDelay)
      else releaseLease(activeKey)
    } catch (error) {
      console.warn(`[NINTH polling] ${activeKey} refresh failed`, error)
    } finally {
      running = false
      if (pending) { pending = false; queueMicrotask(() => execute({ force: true })) }
      else schedule()
    }
  }

  const visibilityChanged = () => {
    clear()
    if (!visible()) {
      if (activeKey) releaseLease(activeKey)
      return
    }
    execute()
  }

  return {
    start() {
      if (!stopped) return
      stopped = false
      document.addEventListener('visibilitychange', visibilityChanged)
      if (immediate) execute({ force: true })
      else schedule()
    },
    trigger() { return execute({ force: true }) },
    stop() {
      stopped = true
      clear()
      document.removeEventListener('visibilitychange', visibilityChanged)
      if (activeKey) releaseLease(activeKey)
    },
  }
}
