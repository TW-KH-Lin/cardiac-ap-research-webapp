const origin = import.meta.env.VITE_API_BASE_URL?.trim().replace(/\/+$/, '') ?? ''

export const API = origin.endsWith('/api') ? origin : `${origin}/api`
