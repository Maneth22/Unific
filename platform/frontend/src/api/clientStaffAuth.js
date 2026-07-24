import { apiClient } from './client'

// Limited client-staff login (an org owner's employee) — mirrors
// clientAuth.js exactly, but against /profiles/client-staff/*.
export async function clientStaffLogin(email, password) {
  const { data } = await apiClient.post('/profiles/client-staff/login', { email, password })
  return data
}

export async function clientStaffRefresh() {
  const { data } = await apiClient.post('/profiles/client-staff/refresh')
  return data
}

export async function clientStaffLogout() {
  await apiClient.post('/profiles/client-staff/logout')
}

export async function clientStaffMe() {
  const { data } = await apiClient.get('/profiles/client-staff/me')
  return data
}
