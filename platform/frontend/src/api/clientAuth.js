import { apiClient } from './client'

export async function clientLogin(email, password) {
  const { data } = await apiClient.post('/profiles/client/login', { email, password })
  return data
}

export async function clientRefresh() {
  const { data } = await apiClient.post('/profiles/client/refresh')
  return data
}

export async function clientLogout() {
  await apiClient.post('/profiles/client/logout')
}

export async function clientMe() {
  const { data } = await apiClient.get('/profiles/client/me')
  return data
}
