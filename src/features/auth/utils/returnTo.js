export const safeReturnTo = value => {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return '/'
  try {
    const target = new URL(value, 'https://ninth.local')
    return target.origin === 'https://ninth.local' && !target.username && !target.password ? value : '/'
  } catch {
    return '/'
  }
}
