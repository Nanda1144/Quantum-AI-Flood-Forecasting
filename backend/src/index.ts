import { pathToFileURL } from 'node:url'
import { config } from './config.ts'
import { createApp } from './app.ts'

/* Bootstrap the HTTP server only when this file is the entry point. */
const isMain = process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href

if (isMain) {
  const app = await createApp()
  app.listen(config.PORT, () => {
    console.log(
      `[backend] listening on http://localhost:${config.PORT} (auth: ${config.AUTH_ENABLED ? 'enabled' : 'DISABLED (demo)'}, mode: ${process.env.DATABASE_MODE ?? 'postgres'})`,
    )
  })
}

export { createApp }