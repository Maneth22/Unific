import { apiClient } from './client'

export const getUsageSummary = () => apiClient.get('/accounts/ai-usage/summary').then((r) => r.data)
export const getUsageForIdentity = (identityId) => apiClient.get(`/profiles/identities/${identityId}/ai-usage`).then((r) => r.data)
