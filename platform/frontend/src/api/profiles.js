import { apiClient } from './client'

// --- Staff: identity tree ---
export const listIdentities = () => apiClient.get('/profiles/identities').then((r) => r.data)
export const createIdentity = (payload) => apiClient.post('/profiles/identities', payload).then((r) => r.data)
export const getIdentity = (id) => apiClient.get(`/profiles/identities/${id}`).then((r) => r.data)
export const moveSubtree = (id, newParentId) =>
  apiClient.post(`/profiles/identities/${id}/move`, { new_parent_id: newParentId }).then((r) => r.data)

// --- Permissions ---
export const getPermission = (id) => apiClient.get(`/profiles/identities/${id}/permission`).then((r) => r.data)
export const updatePermission = (id, payload) => apiClient.put(`/profiles/identities/${id}/permission`, payload).then((r) => r.data)

// --- Profile account ---
export const getAccount = (id) => apiClient.get(`/profiles/identities/${id}/account`).then((r) => r.data)
export const fundAccount = (id, amount, description = '') =>
  apiClient.post(`/profiles/identities/${id}/fund`, { amount, description }).then((r) => r.data)
export const transferCredit = (fromId, toId, amount, description = '') =>
  apiClient.post(`/profiles/identities/${fromId}/transfer`, { to_identity_id: toId, amount, description })

// --- Consent ---
export const listConsent = (id) => apiClient.get(`/profiles/identities/${id}/consent`).then((r) => r.data)
export const recordConsent = (id, payload) => apiClient.post(`/profiles/identities/${id}/consent`, payload).then((r) => r.data)

// --- Client account provisioning (staff-side) ---
export const createClientAccount = (identityId, payload) =>
  apiClient.post(`/profiles/identities/${identityId}/client-account`, payload).then((r) => r.data)

// --- Client registration requests (Admin review queue) ---
export const listRegistrationRequests = (status) =>
  apiClient.get('/profiles/registration-requests', { params: status ? { status_filter: status } : {} }).then((r) => r.data)
export const approveRegistrationRequest = (id) =>
  apiClient.post(`/profiles/registration-requests/${id}/approve`).then((r) => r.data)
export const rejectRegistrationRequest = (id, reason = '') =>
  apiClient.post(`/profiles/registration-requests/${id}/reject`, { reason }).then((r) => r.data)
