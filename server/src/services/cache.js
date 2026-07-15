const entries = new Map()

export const cache = {
  peek(key) {
    const current = entries.get(key)
    return current && !current.pending && current.expiresAt > Date.now() ? current.value : undefined
  },
  async remember(key, ttlMs, resolver) {
    const current = entries.get(key)
    if (current && current.expiresAt > Date.now()) return current.value
    const pending = Promise.resolve().then(resolver)
    entries.set(key, { value: pending, expiresAt: Date.now() + ttlMs, pending: true })
    try {
      const value = await pending
      entries.set(key, { value, expiresAt: Date.now() + ttlMs, pending: false })
      return value
    } catch (error) {
      if (entries.get(key)?.value === pending) entries.delete(key)
      throw error
    }
  },
  clear(prefix = '') {
    for (const key of entries.keys()) if (key.startsWith(prefix)) entries.delete(key)
  },
}
