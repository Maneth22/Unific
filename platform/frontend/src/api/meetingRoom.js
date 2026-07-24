import { apiClient } from './client'

export const listConversations = () => apiClient.get('/meeting-room/conversations').then((r) => r.data)
export const getConversation = (id) => apiClient.get(`/meeting-room/conversations/${id}`).then((r) => r.data)
export const sendManualReply = (id, text) => apiClient.post(`/meeting-room/conversations/${id}/reply`, { text }).then((r) => r.data)

export const listWhatsAppLinks = () => apiClient.get('/meeting-room/whatsapp-links').then((r) => r.data)
export const createWhatsAppLink = (phone_number, identity_id) =>
  apiClient.post('/meeting-room/whatsapp-links', { phone_number, identity_id }).then((r) => r.data)

export const listMeetings = () => apiClient.get('/meeting-room/meetings').then((r) => r.data)
export const getMeeting = (id) => apiClient.get(`/meeting-room/meetings/${id}`).then((r) => r.data)
export const createMeeting = (payload) => apiClient.post('/meeting-room/meetings', payload).then((r) => r.data)
export const joinMeeting = (id) => apiClient.post(`/meeting-room/meetings/${id}/join`).then((r) => r.data)
export const endMeeting = (id) => apiClient.post(`/meeting-room/meetings/${id}/end`).then((r) => r.data)
export const deleteMeeting = (id) => apiClient.delete(`/meeting-room/meetings/${id}`).then((r) => r.data)

export const getConfigBoard = (identityId) => apiClient.get(`/meeting-room/config-board/${identityId}`).then((r) => r.data)
export const updateConfigBoard = (identityId, payload) => apiClient.put(`/meeting-room/config-board/${identityId}`, payload).then((r) => r.data)

export const listArchiveShelf = (shelf) => apiClient.get(`/meeting-room/archive/${shelf}`).then((r) => r.data)
export const createArchiveItem = (payload) => apiClient.post('/meeting-room/archive', payload).then((r) => r.data)

// Dev-only: simulate an inbound WhatsApp message without a real webhook.
export const simulateInboundMessage = (from, text) =>
  apiClient.post('/meeting-room/webhook', { from, text, id: `dev-${Date.now()}` }).then((r) => r.data)
