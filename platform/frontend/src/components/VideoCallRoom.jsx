// Re-export shim — the real implementation moved to ./video-call/ (split
// across VideoCallRoom.jsx/CallLayout.jsx/ParticipantTileBody.jsx/
// CallControlBar.jsx/DeviceErrorBubble.jsx) so the 4 existing call sites
// (ClientMeetingRoomPage.jsx, StaffMeetingsPage.jsx, MeetingScheduler.jsx,
// MeetingJoinPage.jsx) don't need their import paths touched.
export { default } from './video-call/VideoCallRoom'
