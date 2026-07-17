import { apiClient } from './client'

// Fully public — no auth token required. Used by pages rendered outside
// both the staff and client auth providers (org signup, and the
// community-member registration form at /register/:token).
export const submitClientSignup = (payload) =>
  apiClient.post('/profiles/public/client-signup', payload).then((r) => r.data)

export const getInviteInfo = (token) =>
  apiClient.get(`/profiles/public/invite/${token}`).then((r) => r.data)

export const submitMemberRegistration = (token, payload) =>
  apiClient.post(`/profiles/public/invite/${token}/register`, payload).then((r) => r.data)
