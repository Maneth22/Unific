import { apiClient } from './client'

export const listMyIdentities = () => apiClient.get('/profiles/client/identities').then((r) => r.data)
export const getAccountsOverview = () => apiClient.get('/profiles/client/accounts-overview').then((r) => r.data)
export const getMyIdentity = (id) => apiClient.get(`/profiles/client/identities/${id}`).then((r) => r.data)
export const getMyPermission = (id) => apiClient.get(`/profiles/client/identities/${id}/permission`).then((r) => r.data)
export const updateMyPermission = (id, payload) => apiClient.put(`/profiles/client/identities/${id}/permission`, payload).then((r) => r.data)
export const getMyAccount = (id) => apiClient.get(`/profiles/client/identities/${id}/account`).then((r) => r.data)
export const fundMyAccount = (id, amount, description = '') =>
  apiClient.post(`/profiles/client/identities/${id}/fund`, { amount, description }).then((r) => r.data)
export const transferMyCredit = (fromId, toId, amount, description = '') =>
  apiClient.post(`/profiles/client/identities/${fromId}/transfer`, { to_identity_id: toId, amount, description })
