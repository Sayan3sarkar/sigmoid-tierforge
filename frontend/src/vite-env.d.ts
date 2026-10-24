/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** The TierForge API, without the /api suffix, e.g. http://localhost:8001 */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
