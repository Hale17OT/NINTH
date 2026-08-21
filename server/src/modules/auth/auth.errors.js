export class AppError extends Error {
  constructor(message, status = 400, code = 'REQUEST_FAILED') {
    super(message)
    this.name = 'AppError'
    this.status = status
    this.code = code
    this.publicMessage = message
  }
}
