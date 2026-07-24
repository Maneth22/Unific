import { apiClient } from './client'

export const listMyConversations = () => apiClient.get('/meeting-room/client/conversations').then((r) => r.data)
export const getMyConversation = (id) => apiClient.get(`/meeting-room/client/conversations/${id}`).then((r) => r.data)
export const sendMyReply = (id, text) => apiClient.post(`/meeting-room/client/conversations/${id}/reply`, { text }).then((r) => r.data)

export const initiateRoom = (payload) =>
  apiClient.post('/meeting-room/client/conversations/initiate', payload).then((r) => r.data)

export const generateReport = (conversationId, reportType) =>
  apiClient.post(`/meeting-room/client/conversations/${conversationId}/reports`, { report_type: reportType }).then((r) => r.data)
export const listReports = (conversationId) =>
  apiClient.get(`/meeting-room/client/conversations/${conversationId}/reports`).then((r) => r.data)

export const listMyMeetings = () => apiClient.get('/meeting-room/client/meetings').then((r) => r.data)
export const getMyMeeting = (id) => apiClient.get(`/meeting-room/client/meetings/${id}`).then((r) => r.data)
export const joinMyMeeting = (id, identityId) =>
  apiClient.post(`/meeting-room/client/meetings/${id}/join`, identityId ? { identity_id: identityId } : {}).then((r) => r.data)
