import React from 'react'
import { LiveKitRoom, VideoConference } from '@livekit/components-react'
import '@livekit/components-styles'

// Shared by every join surface (staff dashboard, client dashboard, and the
// public passwordless invite page) — one component, three token sources.
// `serverUrl`/`token` come straight from the backend's JoinResponse
// ({ livekit_url, token }); this component never talks to the LiveKit API
// itself, only to the room the backend already authorized.
export default function VideoCallRoom({ serverUrl, token, onDisconnected }) {
  return (
    <LiveKitRoom
      serverUrl={serverUrl}
      token={token}
      connect
      video
      audio
      style={{ height: '80vh' }}
      onDisconnected={onDisconnected}
    >
      <VideoConference />
    </LiveKitRoom>
  )
}
