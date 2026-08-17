import { apiClient } from './client'

export const listConversations = () => apiClient.get('/meeting-room/conversations').then((r) => r.data)
export const getConversation = (id) => apiClient.get(`/meeting-room/conversations/${id}`).then((r) => r.data)
export const sendManualReply = (id, text) => apiClient.post(`/meeting-room/conversations/${id}/reply`, { text }).then((r) => r.data)

export const listWhatsAppLinks = () => apiClient.get('/meeting-room/whatsapp-links').then((r) => r.data)
export const createWhatsAppLink = (phone_number, identity_id) =>
  apiClient.post('/meeting-room/whatsapp-links', { phone_number, identity_id }).then((r) => r.data)

// Static config (unauthenticated) — which languages the scheduler's
// language picker may offer right now. Single source of truth lives in
// the backend's live_translation.SELECTABLE_LANGUAGES.
export const getTranslationLanguages = () =>
  apiClient.get('/meeting-room/public/translation-languages').then((r) => r.data)

export const listMeetings = () => apiClient.get('/meeting-room/meetings').then((r) => r.data)
export const listMyMeetings = () => apiClient.get('/meeting-room/my-meetings').then((r) => r.data)
export const getMeeting = (id) => apiClient.get(`/meeting-room/meetings/${id}`).then((r) => r.data)
export const createMeeting = (payload) => apiClient.post('/meeting-room/meetings', payload).then((r) => r.data)
export const joinMeeting = (id) => apiClient.post(`/meeting-room/meetings/${id}/join`).then((r) => r.data)
export const endMeeting = (id) => apiClient.post(`/meeting-room/meetings/${id}/end`).then((r) => r.data)
export const deleteMeeting = (id) => apiClient.delete(`/meeting-room/meetings/${id}`).then((r) => r.data)
// Adds one more identity or staff participant to an already-scheduled/live
// meeting — payload is { identity_id } or { staff_user_id }, exactly one set.
export const addParticipant = (id, payload) =>
  apiClient.post(`/meeting-room/meetings/${id}/participants`, payload).then((r) => r.data)

// Persisted in-call chat history (see live_agents.chat_relay, which
// writes these rows live) — each row's `translations` dict carries every
// language a live participant actually needed; ChatPanel.jsx picks out
// its own chat_language, falling back to original_text if absent.
export const getMeetingChat = (id) => apiClient.get(`/meeting-room/meetings/${id}/chat`).then((r) => r.data)
// Regular-staff counterpart of getMeetingChat above — same shape, but hits
// the require_any_staff-gated /my-meetings/{id}/chat route (scoped to
// meetings this staff account participates in) instead of the admin-only
// one, since StaffMeetingsPage.jsx isn't restricted to admins.
export const getMyStaffMeetingChat = (id) => apiClient.get(`/meeting-room/my-meetings/${id}/chat`).then((r) => r.data)

// Force-flushes today's Redis-cached WhatsApp turns into Postgres Message
// rows right now, instead of waiting for the end-of-day cron
// (app.agents.whatsapp_community.scheduler) — lets the WhatsApp Messages
// admin page show a just-sent test message immediately.
export const flushWhatsAppSessions = () => apiClient.post('/meeting-room/admin/sessions/flush').then((r) => r.data)

export const getConfigBoard = (identityId) => apiClient.get(`/meeting-room/config-board/${identityId}`).then((r) => r.data)
export const updateConfigBoard = (identityId, payload) => apiClient.put(`/meeting-room/config-board/${identityId}`, payload).then((r) => r.data)

export const listArchiveShelf = (shelf) => apiClient.get(`/meeting-room/archive/${shelf}`).then((r) => r.data)
export const createArchiveItem = (payload) => apiClient.post('/meeting-room/archive', payload).then((r) => r.data)

// Dev-only: simulate an inbound WhatsApp message without a real webhook.
export const simulateInboundMessage = (from, text) =>
  apiClient.post('/meeting-room/webhook', { from, text, id: `dev-${Date.now()}` }).then((r) => r.data)
