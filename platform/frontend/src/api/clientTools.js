import { apiClient } from './client'

// Client-dashboard equivalents of api/tools.js — scoped to the caller's
// own identity subtree (require_identity_scope, enforced server-side).
// Only ever covers the five cascading slots (reply_generator, comms_agent,
// meeting_stt, meeting_tts, meeting_translation) — whatsapp_send/
// video_provider are staff-global only and never appear here.
export const listClientToolCatalog = (slot) =>
  apiClient.get('/tools/client/catalog', { params: slot ? { slot } : {} }).then((r) => r.data)
export const getClientIdentityToolConfig = (identityId) =>
  apiClient.get(`/tools/client/identities/${identityId}`).then((r) => r.data)
export const updateClientIdentityToolConfig = (identityId, payload) =>
  apiClient.put(`/tools/client/identities/${identityId}`, payload).then((r) => r.data)
