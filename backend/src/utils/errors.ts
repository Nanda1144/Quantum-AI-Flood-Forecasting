/** Internal client/envelope error used before mapping to an `AppError`. */

export class EnvelopeError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message)
    this.name = 'EnvelopeError'
  }
}