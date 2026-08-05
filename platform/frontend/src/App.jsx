import React from 'react'
import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import { ClientAuthProvider, useClientAuth } from './context/ClientAuthContext'
import ProtectedRoute from './routes/ProtectedRoute'
import RequireAdmin from './routes/RequireAdmin'
import ScopeRoute from './routes/ScopeRoute'
import StaffDashboardLayout from './layouts/StaffDashboardLayout'
import StaffPortalLayout from './layouts/StaffPortalLayout'
import ClientDashboardLayout from './layouts/ClientDashboardLayout'
import PublicLayout from './layouts/PublicLayout'
import LoginPage from './pages/LoginPage'
import ClientLoginPage from './pages/ClientLoginPage'
import ClientSignupPage from './pages/ClientSignupPage'
import MemberRegistrationPage from './pages/MemberRegistrationPage'
import MeetingJoinPage from './pages/MeetingJoinPage'
import StaffHomePage from './pages/StaffHomePage'
import StaffManagementPage from './pages/StaffManagementPage'
import StaffRegistrationRequestsPage from './pages/StaffRegistrationRequestsPage'
import StaffTasksPage from './pages/StaffTasksPage'
import StaffInboxPage from './pages/StaffInboxPage'
import StaffMeetingsPage from './pages/StaffMeetingsPage'
import ClientAccountsPage from './pages/ClientAccountsPage'
import ClientCommunitiesPage from './pages/ClientCommunitiesPage'
import ClientCommunityDetailPage from './pages/ClientCommunityDetailPage'
import ClientMeetingRoomPage from './pages/ClientMeetingRoomPage'
import ClientInboxPage from './pages/ClientInboxPage'
import ClientServicesPage from './pages/ClientServicesPage'
import LandingPage from './pages/LandingPage'
import AboutPage from './pages/AboutPage'
import ContactPage from './pages/ContactPage'
import ConnectionLostPage from './pages/ConnectionLostPage'
import PermissionDeniedPage from './pages/PermissionDeniedPage'
import NotFoundPage from './pages/NotFoundPage'
import AccountsRoomHome from './rooms/accounts/AccountsRoomHome'
import ProfilesRoomHome from './rooms/profiles/ProfilesRoomHome'
import MeetingRoomHome from './rooms/meeting-room/MeetingRoomHome'

// Only one audience's AuthProvider is ever mounted at a time — staff and
// client share one in-memory access-token slot (api/client.js), which is
// safe only because their route subtrees never overlap. Each area also
// gate-checks connectionError (set only when the provider's mount-time
// silent-refresh call fails with a genuine network error, not a normal
// "not logged in" 401) so a fully unreachable backend shows
// ConnectionLostPage instead of a misleading login/empty-dashboard flash.
function StaffAreaGate() {
  const { connectionError } = useAuth()
  if (connectionError) return <ConnectionLostPage />
  return <Outlet />
}

function StaffArea() {
  return (
    <AuthProvider>
      <StaffAreaGate />
    </AuthProvider>
  )
}

function ClientAreaGate() {
  const { connectionError } = useClientAuth()
  if (connectionError) return <ConnectionLostPage />
  return <Outlet />
}

function ClientArea() {
  return (
    <ClientAuthProvider>
      <ClientAreaGate />
    </ClientAuthProvider>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Public marketing site — no auth provider mounted at all. */}
        <Route element={<PublicLayout />}>
          <Route path="/" element={<LandingPage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="/contact" element={<ContactPage />} />
        </Route>

        <Route element={<StaffArea />}>
          {/* Staff/admin login — framed as joining UNIFIC as a supporter. */}
          <Route path="/support/login" element={<LoginPage />} />

          <Route element={<ProtectedRoute />}>
            {/* Admin tier: the full dashboard — every existing room. */}
            <Route element={<RequireAdmin />}>
              <Route element={<StaffDashboardLayout />}>
                <Route path="/staff" element={<StaffHomePage />} />
                <Route path="/staff-management" element={<StaffManagementPage />} />
                <Route path="/registration-requests" element={<StaffRegistrationRequestsPage />} />
                <Route path="/accounts" element={<AccountsRoomHome />} />
                <Route path="/profiles" element={<ProfilesRoomHome />} />
                <Route path="/meeting-room" element={<MeetingRoomHome />} />
              </Route>
            </Route>

            {/* Regular staff tier: tasks + inbox only, no client/cost data. */}
            <Route element={<StaffPortalLayout />}>
              <Route path="/portal" element={<StaffTasksPage />} />
              <Route path="/portal/inbox" element={<StaffInboxPage />} />
              <Route path="/portal/meetings" element={<StaffMeetingsPage />} />
            </Route>
          </Route>
        </Route>

        <Route element={<ClientArea />}>
          {/* The "normal" login now lives at the top-level path. */}
          <Route path="/login" element={<ClientLoginPage />} />
          <Route path="/client/signup" element={<ClientSignupPage />} />

          <Route element={<ScopeRoute />}>
            <Route path="/client" element={<ClientDashboardLayout />}>
              <Route index element={<ClientAccountsPage />} />
              <Route path="communities" element={<ClientCommunitiesPage />} />
              <Route path="communities/:groupId" element={<ClientCommunityDetailPage />} />
              <Route path="meeting-room" element={<ClientMeetingRoomPage />} />
              <Route path="inbox" element={<ClientInboxPage />} />
              <Route path="services" element={<ClientServicesPage />} />
            </Route>
          </Route>
        </Route>

        {/* Compatibility redirect for the old client-login path — no auth
            context needed for a bare Navigate. */}
        <Route path="/client/login" element={<Navigate to="/login" replace />} />

        {/* Fully public — no auth wrapper at all, reached from a shared link. */}
        <Route path="/register/:token" element={<MemberRegistrationPage />} />
        <Route path="/meeting-room/join/:token" element={<MeetingJoinPage />} />

        <Route path="/403" element={<PermissionDeniedPage />} />
        <Route path="/404" element={<NotFoundPage />} />
        <Route path="*" element={<Navigate to="/404" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
