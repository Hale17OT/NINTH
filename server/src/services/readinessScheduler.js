import { spawn } from 'node:child_process'

let running = false
let scheduled

const nextNightlyDelay = () => {
  const now = new Date()
  const hour = Math.max(0, Math.min(23, Number(process.env.NINTH_READINESS_HOUR ?? 3)))
  const minute = Math.max(0, Math.min(59, Number(process.env.NINTH_READINESS_MINUTE ?? 45)))
  const next = new Date(now)
  next.setHours(hour, minute, 0, 0)
  if (next <= now) next.setDate(next.getDate() + 1)
  return Math.max(1_000, next.getTime() - now.getTime())
}

export const refreshModelReadiness = () => {
  if (running || process.env.NINTH_READINESS_REFRESH === '0') return false
  running = true
  const command = process.env.NINTH_PYTHON || (process.platform === 'win32' ? 'python' : 'python3')
  const child = spawn(command, ['-m', 'ml.multisport.refresh_readiness', '--max-age-hours', '6'], {
    cwd: process.cwd(), windowsHide: true, stdio: 'ignore',
  })
  child.once('error', () => { running = false })
  child.once('exit', () => { running = false })
  return true
}

export const startReadinessScheduler = () => {
  if (process.env.NINTH_READINESS_REFRESH === '0') return
  const scheduleNext = () => {
    scheduled = setTimeout(() => {
      refreshModelReadiness()
      scheduleNext()
    }, nextNightlyDelay())
    scheduled.unref?.()
  }
  scheduleNext()
}
