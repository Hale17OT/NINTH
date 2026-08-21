import { authConfig } from '../../config/auth.js'
import { authService } from '../auth/auth.service.js'
import { clearSessionCookieOptions } from '../auth/session.service.js'
import { userService } from './user.service.js'

export const userController = {
  account: async (req, res) => res.json(await userService.account(req.auth.user.id)),
  profile: async (req, res) => res.json(await userService.updateProfile(req.auth.user.id, req.validated)),
  preferences: async (req, res) => res.json(await userService.updatePreferences(req.auth.user.id, req.validated)),
  changePassword: async (req, res) => res.json(await authService.changePassword(req.auth.user.id, req.validated, req)),
  sessions: async (req, res) => res.json(await userService.sessions(req.auth.user.id, req.auth.session.id)),
  revokeSession: async (req, res) => {
    const result = await userService.revokeSession(req.auth.user.id, req.params.id, req.auth.session.id)
    if (result.current) res.clearCookie(authConfig.sessionCookieName, clearSessionCookieOptions())
    res.json(result)
  },
}
