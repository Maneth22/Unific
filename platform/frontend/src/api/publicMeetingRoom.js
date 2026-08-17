import { apiClient } from './client'

// Fully public — no auth token required. Used by the passwordless meeting
// join page at /meeting-room/join/:token (mirrors api/publicRegistration.js).
export const getJoinInfo = (token) =>
  apiClient.get(`/meeting-room/public/join/${token}`).then((r) => r.data)

export const submitPublicJoin = (token) =>
  apiClient.post(`/meeting-room/public/join/${token}`).then((r) => r.data)

// The meeting-wide open/shareable invite (kind="open" — see getJoinInfo's
// `kind` field) — a separate endpoint from the personal one above since
// it needs a guest display name (no known participant to greet) and
// mints a fresh identity on every call, so many different people can use
// the same link at once.
export const submitGuestJoin = (token, guestName) =>
  apiClient.post(`/meeting-room/public/open-join/${token}`, { guest_name: guestName }).then((r) => r.data)

// Persisted in-call chat history — token-keyed (the same trust boundary
// as the join flow itself), not meeting-id-keyed, since a guest has no
// other durable credential.
export const getPublicMeetingChat = (token) => apiClient.get(`/meeting-room/public/join/${token}/chat`).then((r) => r.data)
