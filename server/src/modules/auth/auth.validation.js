import { z } from 'zod'

const email = z.string().trim().email('Enter a valid email address.').max(320)
const displayName = z.string().trim().min(2, 'Use at least 2 characters.').max(80, 'Use 80 characters or fewer.')
const password = z.string()
  .min(10, 'Use at least 10 characters.')
  .max(256, 'Use 256 characters or fewer.')
  .regex(/[a-z]/, 'Add a lowercase letter.')
  .regex(/[A-Z]/, 'Add an uppercase letter.')
  .regex(/[^A-Za-z0-9]/, 'Add a symbol.')
const token = z.string().min(32, 'This link is invalid.').max(512)

export const registerSchema = z.object({
  displayName,
  email,
  password,
  passwordConfirmation: z.string(),
  termsAccepted: z.literal(true, { error: 'Accept the Terms and Privacy Policy to continue.' }),
  remember: z.boolean().optional().default(true),
}).superRefine((value, context) => {
  if (value.password !== value.passwordConfirmation) context.addIssue({ code: 'custom', path: ['passwordConfirmation'], message: 'Passwords do not match.' })
})

export const loginSchema = z.object({
  email,
  password: z.string().min(1, 'Enter your password.').max(256),
  remember: z.boolean().optional().default(false),
})

export const forgotPasswordSchema = z.object({ email })
export const resetPasswordSchema = z.object({ token, password, passwordConfirmation: z.string() }).superRefine((value, context) => {
  if (value.password !== value.passwordConfirmation) context.addIssue({ code: 'custom', path: ['passwordConfirmation'], message: 'Passwords do not match.' })
})
export const verifyEmailSchema = z.object({ token })
export const changePasswordSchema = z.object({
  currentPassword: z.string().min(1, 'Enter your current password.'),
  password,
  passwordConfirmation: z.string(),
}).superRefine((value, context) => {
  if (value.password !== value.passwordConfirmation) context.addIssue({ code: 'custom', path: ['passwordConfirmation'], message: 'Passwords do not match.' })
})
export const updateProfileSchema = z.object({ displayName })
export const preferenceSchema = z.object({
  preferredSport: z.string().trim().max(50).nullable().optional(),
  preferredLeague: z.string().trim().max(100).nullable().optional(),
  oddsFormat: z.enum(['DECIMAL', 'AMERICAN', 'FRACTIONAL']).optional(),
  timezone: z.string().trim().min(1).max(100).optional(),
  notificationPreferences: z.record(z.string(), z.boolean()).optional(),
})
