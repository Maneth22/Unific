import { apiClient } from './client'

export async function staffLogin(email, password) {
  const { data } = await apiClient.post('/auth/staff/login', { email, password })
  return data
}

export async function staffBootstrap(email, password, full_name) {
  const { data } = await apiClient.post('/auth/staff/bootstrap', { email, password, full_name })
  return data
}

export async function staffRefresh() {
  const { data } = await apiClient.post('/auth/staff/refresh')
  return data
}

export async function staffLogout() {
  await apiClient.post('/auth/staff/logout')
}

export async function staffMe() {
  const { data } = await apiClient.get('/auth/staff/me')
  return data
}

export async function createStaff(email, password, full_name) {
  const { data } = await apiClient.post('/auth/staff/staff', { email, password, full_name })
  return data
}

export async function grantRoomAccess(staffId, room, permission) {
  const { data } = await apiClient.post(`/auth/staff/staff/${staffId}/room-access`, { room, permission })
  return data
}
