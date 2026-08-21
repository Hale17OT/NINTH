import nodemailer from 'nodemailer'
import { authConfig } from '../../config/auth.js'

const testOutbox = []
let transporter

const smtpConfigured = () => Boolean(process.env.SMTP_HOST && process.env.SMTP_USER && process.env.SMTP_PASSWORD && process.env.SMTP_FROM)

const getTransporter = () => {
  if (!smtpConfigured()) return null
  if (!transporter) transporter = nodemailer.createTransport({
    host: process.env.SMTP_HOST,
    port: Number(process.env.SMTP_PORT || 587),
    secure: String(process.env.SMTP_SECURE || '').toLowerCase() === 'true' || Number(process.env.SMTP_PORT) === 465,
    auth: { user: process.env.SMTP_USER, pass: process.env.SMTP_PASSWORD },
  })
  return transporter
}

const send = async message => {
  if (process.env.NODE_ENV === 'test') {
    testOutbox.push(message)
    return { delivered: true, provider: 'test' }
  }
  const client = getTransporter()
  if (!client) {
    if (authConfig.production) throw new Error('Production email delivery is not configured.')
    console.info(`[NINTH email] ${message.kind} email suppressed because SMTP is not configured.`)
    return { delivered: false, provider: 'development' }
  }
  await client.sendMail({
    from: process.env.SMTP_FROM,
    to: message.to,
    subject: message.subject,
    text: message.text,
    html: message.html,
  })
  return { delivered: true, provider: 'smtp' }
}

const escapeHtml = value => String(value).replace(/[&<>"']/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
})[character])
const emailFrame = (title, copy, action, actionUrl) => `<!doctype html><html><body style="margin:0;background:#0a0c0b;color:#f4f7f1;font-family:Arial,sans-serif"><div style="max-width:560px;margin:0 auto;padding:48px 24px"><div style="color:#d6ff61;font-size:12px;letter-spacing:.18em">NINTH / ACCOUNT SECURITY</div><h1 style="font-size:32px;margin:18px 0 10px">${escapeHtml(title)}</h1><p style="color:#b4bdb3;line-height:1.7">${escapeHtml(copy)}</p><a href="${escapeHtml(actionUrl)}" style="display:inline-block;margin-top:22px;padding:14px 18px;background:#d6ff61;color:#10130f;text-decoration:none;font-weight:700">${escapeHtml(action)}</a><p style="margin-top:30px;color:#7e887e;font-size:12px;line-height:1.6">If you did not request this, you can safely ignore the message. The link expires automatically.</p></div></body></html>`

export const emailService = {
  async sendVerificationEmail({ to, displayName, token }) {
    const url = new URL('/auth/verify-email', authConfig.appUrl)
    url.searchParams.set('token', token)
    return send({ kind: 'verification', to, subject: 'Verify your NINTH account', url: url.toString(), text: `Hi ${displayName}, verify your NINTH account: ${url}`, html: emailFrame('Verify your account', `Hi ${displayName}. Confirm your email to secure your saved predictions and builders.`, 'Verify email', url) })
  },
  async sendPasswordResetEmail({ to, displayName, token }) {
    const url = new URL('/auth/reset-password', authConfig.appUrl)
    url.searchParams.set('token', token)
    return send({ kind: 'password-reset', to, subject: 'Reset your NINTH password', url: url.toString(), text: `Hi ${displayName}, reset your NINTH password: ${url}`, html: emailFrame('Reset your password', `Hi ${displayName}. Use this secure link to choose a new password.`, 'Reset password', url) })
  },
  async sendSecurityNotification({ to, displayName, subject, copy }) {
    const url = new URL('/account', authConfig.appUrl)
    return send({ kind: 'security', to, subject, text: `Hi ${displayName}, ${copy}`, html: emailFrame(subject, copy, 'Review account', url) })
  },
  configured: smtpConfigured,
}

export const __testEmailOutbox = {
  all: () => [...testOutbox],
  clear: () => { testOutbox.length = 0 },
}
