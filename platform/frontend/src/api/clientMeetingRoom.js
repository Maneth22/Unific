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
export const scheduleMyMeeting = (payload) => apiClient.post('/meeting-room/client/meetings', payload).then((r) => r.data)
export const endMyMeeting = (id) => apiClient.post(`/meeting-room/client/meetings/${id}/end`).then((r) => r.data)
export const joinMyMeeting = (id, identityId) =>
  apiClient.post(`/meeting-room/client/meetings/${id}/join`, identityId ? { identity_id: identityId } : {}).then((r) => r.data)
// Re-attempts starting live translation for a meeting whose pipeline
// failed or crashed — any client whose scope covers this meeting (see
// TranslatorParticipant.jsx's Retry button).
export const retryMyMeetingTranslation = (id) =>
  apiClient.post(`/meeting-room/client/meetings/${id}/translation/retry`).then((r) => r.data)
// Adds one more identity (from the client's own scope) to an
// already-scheduled/live meeting.
export const addMyParticipant = (id, identityId) =>
  apiClient.post(`/meeting-room/client/meetings/${id}/participants`, { identity_id: identityId }).then((r) => r.data)

// Persisted in-call chat history — see api/meetingRoom.js's getMeetingChat
// for the shape.
export const getMyMeetingChat = (id) => apiClient.get(`/meeting-room/client/meetings/${id}/chat`).then((r) => r.data)
