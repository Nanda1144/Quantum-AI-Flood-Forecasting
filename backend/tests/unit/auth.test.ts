import '../helpers/env.js'
import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { AuthService } from '../../src/services/auth.service.ts'
import { config } from '../../src/config.ts'
import { AppError, ErrorCodes } from '../../src/envelope.ts'

describe('AuthService', () => {
  const auth = new AuthService(config)

  it('logs in a valid user and issues a JWT', () => {
    const { token, user } = auth.login('admin', 'qflare-admin')
    assert.equal(user.username, 'admin')
    assert.equal(user.role, 'admin')
    assert.equal(typeof token, 'string')
    assert.ok(token.split('.').length === 3)
  })

  it('rejects an unknown username', () => {
    assert.throws(() => auth.login('nobody', 'x'), (err: AppError) => {
      assert.equal(err.status, 401)
      assert.equal(err.code, ErrorCodes.UNAUTHORIZED)
      return true
    })
  })

  it('rejects a wrong password', () => {
    assert.throws(() => auth.login('admin', 'wrong-password'), (err: Error) => err instanceof AppError)
  })

  it('verifyToken round-trips the principal', () => {
    const { token } = auth.login('operator', 'qflare-operator')
    const principal = auth.verifyToken(token)
    assert.deepEqual(principal, { username: 'operator', role: 'operator' })
  })

  it('verifyToken returns null for a tampered token', () => {
    const { token } = auth.login('operator', 'qflare-operator')
    const [h, p] = token.split('.')
    const tampered = `${h}.${p}x.${token.split('.')[2]}`
    assert.equal(auth.verifyToken(tampered), null)
  })

  it('verifyToken rejects a token signed with a different secret', () => {
    const other = new AuthService({ ...config, JWT_SECRET: 'a-completely-different-secret-1' })
    const { token } = other.login('operator', 'qflare-operator')
    assert.equal(auth.verifyToken(token), null)
  })
})