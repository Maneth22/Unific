import { apiClient } from './client'

// --- Admin: categories (create) + staff directory ---
export const createCategory = (payload) => apiClient.post('/staff-directory/categories', payload).then((r) => r.data)
export const listStaff = () => apiClient.get('/staff-directory/staff').then((r) => r.data)
export const updateStaff = (id, payload) => apiClient.patch(`/staff-directory/staff/${id}`, payload).then((r) => r.data)

// --- Any staff: category list (to show their own label) ---
export const listCategories = () => apiClient.get('/staff-directory/categories').then((r) => r.data)

// --- Any staff: minimal id+name list, to pick an inbox recipient ---
export const listStaffLite = () => apiClient.get('/staff-directory/staff/lite').then((r) => r.data)
