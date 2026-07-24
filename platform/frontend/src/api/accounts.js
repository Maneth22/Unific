import { apiClient } from './client'

// --- Registry ---
export const listRegistry = () => apiClient.get('/accounts/registry').then((r) => r.data)
export const createRegistryEntry = (payload) => apiClient.post('/accounts/registry', payload).then((r) => r.data)
export const updateRegistryEntry = (id, payload) => apiClient.put(`/accounts/registry/${id}`, payload).then((r) => r.data)
export const revealSecret = (id) => apiClient.post(`/accounts/registry/${id}/reveal`).then((r) => r.data)

// --- Financial ---
export const listFinancialRecords = () => apiClient.get('/accounts/financial/records').then((r) => r.data)
export const createFinancialRecord = (payload) => apiClient.post('/accounts/financial/records', payload).then((r) => r.data)
export const getFinancialSummary = () => apiClient.get('/accounts/financial/summary').then((r) => r.data)

// --- API Monitor ---
export const listApiMonitor = () => apiClient.get('/accounts/api-monitor').then((r) => r.data)
export const createApiMonitorEntry = (payload) => apiClient.post('/accounts/api-monitor', payload).then((r) => r.data)
export const updateApiMonitorEntry = (id, payload) => apiClient.put(`/accounts/api-monitor/${id}`, payload).then((r) => r.data)

// --- Calendar ---
export const listCalendar = () => apiClient.get('/accounts/calendar').then((r) => r.data)
export const createCalendarEvent = (payload) => apiClient.post('/accounts/calendar', payload).then((r) => r.data)

// --- Archive ---
export const listArchiveShelf = (shelf) => apiClient.get(`/accounts/archive/${shelf}`).then((r) => r.data)
export const createArchiveItem = (payload) => apiClient.post('/accounts/archive', payload).then((r) => r.data)

// --- Administrative agent ---
export const getAdministrativeSummary = () => apiClient.get('/accounts/administrative-summary').then((r) => r.data)

// --- Cost dashboard (timeline + drill-down) ---
export const getCostTimeseries = (bucket = 'day', groupBy = 'model') =>
  apiClient.get('/accounts/cost-timeseries', { params: { bucket, group_by: groupBy } }).then((r) => r.data)
export const getUsageByClientNeed = () => apiClient.get('/accounts/ai-usage/by-client-need').then((r) => r.data)
export const getFinancialTimeseries = (bucket = 'day') =>
  apiClient.get('/accounts/financial-timeseries', { params: { bucket } }).then((r) => r.data)
