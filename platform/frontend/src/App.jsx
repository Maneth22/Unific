import React from 'react'
import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import { ClientAuthProvider } from './context/ClientAuthContext'
import ProtectedRoute from './routes/ProtectedRoute'
import RoomRoute from './routes/RoomRoute'
import ScopeRoute from './routes/ScopeRoute'
import StaffDashboardLayout from './layouts/StaffDashboardLayout'
import ClientDashboardLayout from './layouts/ClientDashboardLayout'
import LoginPage from './pages/LoginPage'
import ClientLoginPage from './pages/ClientLoginPage'
import StaffHomePage from './pages/StaffHomePage'
import StaffManagementPage from './pages/StaffManagementPage'
import ClientAccountsPage from './pages/ClientAccountsPage'
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

              <Route element={<RoomRoute room="accounts" />}>
                <Route path="/accounts" element={<AccountsRoomHome />} />
              </Route>

              <Route element={<RoomRoute room="profiles" />}>
                <Route path="/profiles" element={<ProfilesRoomHome />} />
              </Route>

              <Route element={<RoomRoute room="meeting_room" />}>
                <Route path="/meeting-room" element={<MeetingRoomHome />} />
              </Route>
            </Route>
          </Route>
        </Route>

        <Route path="/client" element={<ClientArea />}>
          <Route path="login" element={<ClientLoginPage />} />

          <Route element={<ScopeRoute />}>
            <Route element={<ClientDashboardLayout />}>
              <Route index element={<ClientAccountsPage />} />
              <Route path="meeting-room" element={<ClientMeetingRoomPage />} />
            </Route>
          </Route>
        </Route>

        <Route path="/404" element={<NotFoundPage />} />
        <Route path="*" element={<Navigate to="/404" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
