import { apiClient } from './client'

// --- Admin: assign + dashboard ---
export const createTask = (payload) => apiClient.post('/tasking/tasks', payload).then((r) => r.data)
export const listTasksDashboard = () => apiClient.get('/tasking/tasks').then((r) => r.data)
export const listConcerns = () => apiClient.get('/tasking/tasks/concerns').then((r) => r.data)

// --- Any staff: own tasks/updates ---
export const listMyTasks = () => apiClient.get('/tasking/tasks/mine').then((r) => r.data)
export const getTask = (id) => apiClient.get(`/tasking/tasks/${id}`).then((r) => r.data)
export const addTaskUpdate = (id, payload) => apiClient.post(`/tasking/tasks/${id}/updates`, payload).then((r) => r.data)

// --- Any staff: inbox ---
export const listInbox = () => apiClient.get('/tasking/inbox').then((r) => r.data)
export const sendMessage = (payload) => apiClient.post('/tasking/inbox', payload).then((r) => r.data)
export const markMessageRead = (id) => apiClient.patch(`/tasking/inbox/${id}/read`).then((r) => r.data)
