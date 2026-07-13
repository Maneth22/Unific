import axios from 'axios'

// The access token lives only in memory (module-scoped), never
// localStorage — an upgrade over the prototype's localStorage token,
// since a short-lived in-memory token is far less useful to an XSS
// payload. Persistence across reloads comes from the httpOnly refresh
// cookie (see AuthContext's silent-refresh-on-load).
let accessToken = null
let onUnauthorized = null
// Which refresh endpoint a 401 retry should use — set by whichever
// AuthProvider (staff or client) is currently mounted. Defaults to staff
// since that's the app's default entry point.
let refreshEndpoint = '/auth/staff/refresh'

export function setAccessToken(token) {
  accessToken = token
}

export function getAccessToken() {
  return accessToken
}

export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler
}

export function setRefreshEndpoint(endpoint) {
  refreshEndpoint = endpoint
}

export const apiClient = axios.create({
  baseURL: '/api',
  withCredentials: true, // send the httpOnly refresh cookie on refresh calls
})

apiClient.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`
  }
  return config
})

let refreshPromise = null

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { config, response } = error
    if (response?.status === 401 && !config._retried && !config.url?.includes('/refresh')) {
      config._retried = true
      try {
        if (!refreshPromise) {
          refreshPromise = apiClient
            .post(refreshEndpoint)
            .finally(() => {
              refreshPromise = null
            })
        }
        const refreshResponse = await refreshPromise
        setAccessToken(refreshResponse.data.access_token)
        config.headers.Authorization = `Bearer ${refreshResponse.data.access_token}`
        return apiClient(config)
      } catch (refreshError) {
        setAccessToken(null)
        if (onUnauthorized) onUnauthorized()
        return Promise.reject(refreshError)
      }
    }
    return Promise.reject(error)
  }
)
