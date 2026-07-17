import React from 'react'
import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import { ClientAuthProvider } from './context/ClientAuthContext'
import ProtectedRoute from './routes/ProtectedRoute'
import ScopeRoute from './routes/ScopeRoute'
import StaffDashboardLayout from './layouts/StaffDashboardLayout'
import ClientDashboardLayout from './layouts/ClientDashboardLayout'
import LoginPage from './pages/LoginPage'
import ClientLoginPage from './pages/ClientLoginPage'
import ClientSignupPage from './pages/ClientSignupPage'
import MemberRegistrationPage from './pages/MemberRegistrationPage'
import StaffHomePage from './pages/StaffHomePage'
import StaffManagementPage from './pages/StaffManagementPage'
import StaffRegistrationRequestsPage from './pages/StaffRegistrationRequestsPage'
import ClientAccountsPage from './pages/ClientAccountsPage'
import ClientCommunitiesPage from './pages/ClientCommunitiesPage'
import ClientCommunityDetailPage from './pages/ClientCommunityDetailPage'
import ClientMeetingRoomPage from './pages/ClientMeetingRoomPage'
import NotFoundPage from './pages/NotFoundPage'
import AccountsRoomHome from './rooms/accounts/AccountsRoomHome'
import ProfilesRoomHome from './rooms/profiles/ProfilesRoomHome'
import MeetingRoomHome from './rooms/meeting-room/MeetingRoomHome'

// Only one audience's AuthProvider is ever mounted at a time — staff and
// client share one in-memory access-token slot (api/client.js), which is
// safe only because their route subtrees never overlap.
function StaffArea() {
  return (
    <AuthProvider>
      <Outlet />
    </AuthProvider>
  )
}

function ClientArea() {
  return (
    <ClientAuthProvider>
      <Outlet />
    </ClientAuthProvider>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<StaffArea />}>
          <Route path="/login" element={<LoginPage />} />

          <Route element={<ProtectedRoute />}>
            <Route element={<StaffDashboardLayout />}>
              <Route path="/" element={<StaffHomePage />} />
              <Route path="/staff-management" element={<StaffManagementPage />} />
              <Route path="/registration-requests" element={<StaffRegistrationRequestsPage />} />
              <Route path="/accounts" element={<AccountsRoomHome />} />
              <Route path="/profiles" element={<ProfilesRoomHome />} />
              <Route path="/meeting-room" element={<MeetingRoomHome />} />
            </Route>
          </Route>
        </Route>

        <Route path="/client" element={<ClientArea />}>
          <Route path="login" element={<ClientLoginPage />} />
          <Route path="signup" element={<ClientSignupPage />} />

          <Route element={<ScopeRoute />}>
            <Route element={<ClientDashboardLayout />}>
              <Route index element={<ClientAccountsPage />} />
              <Route path="communities" element={<ClientCommunitiesPage />} />
              <Route path="communities/:groupId" element={<ClientCommunityDetailPage />} />
              <Route path="meeting-room" element={<ClientMeetingRoomPage />} />
            </Route>
          </Route>
        </Route>

        {/* Fully public — no auth wrapper at all, reached from a shared link. */}
        <Route path="/register/:token" element={<MemberRegistrationPage />} />

        <Route path="/404" element={<NotFoundPage />} />
        <Route path="*" element={<Navigate to="/404" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
