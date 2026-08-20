import { apiClient } from './client'

// --- Staff: catalog ---
export const listToolCatalog = (slot) =>
  apiClient.get('/tools/catalog', { params: slot ? { slot } : {} }).then((r) => r.data)
export const setToolCatalogEntryEnabled = (slot, toolKey, isEnabled) =>
  apiClient.patch(`/tools/catalog/${slot}/${toolKey}`, { is_enabled: isEnabled }).then((r) => r.data)

// --- Staff: global (system-wide) selection ---
export const listGlobalToolSelections = () => apiClient.get('/tools/global').then((r) => r.data)
export const updateGlobalToolSelection = (slot, payload) =>
  apiClient.put(`/tools/global/${slot}`, payload).then((r) => r.data)

// --- Staff: per-identity override ---
export const getIdentityToolConfig = (identityId) =>
  apiClient.get(`/tools/identities/${identityId}`).then((r) => r.data)
export const updateIdentityToolConfig = (identityId, payload) =>
  apiClient.put(`/tools/identities/${identityId}`, payload).then((r) => r.data)
