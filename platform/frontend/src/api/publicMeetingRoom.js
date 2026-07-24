import { apiClient } from './client'

// Fully public — no auth token required. Used by the passwordless meeting
// join page at /meeting-room/join/:token (mirrors api/publicRegistration.js).
export const getJoinInfo = (token) =>
  apiClient.get(`/meeting-room/public/join/${token}`).then((r) => r.data)

export const submitPublicJoin = (token) =>
  apiClient.post(`/meeting-room/public/join/${token}`).then((r) => r.data)
