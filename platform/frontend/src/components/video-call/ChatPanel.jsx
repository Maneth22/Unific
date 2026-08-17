import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useRoomContext } from '@livekit/components-react'
import { CHAT_TOPIC, CHAT_TRANSLATED_TOPIC } from './callConstants'

// Custom chat panel replacing @livekit/components-react's prefab <Chat>
// (which has no concept of "original + translated together"). Sends the
// original message as JSON on CHAT_TOPIC (the same topic the prefab would
// have used, by LiveKit's own convention — the backend's live_agents
// chat_relay listens on it, and any same-language reader gets the plain
// original straight off this broadcast, per the backend's dedup rule),
// and listens for a translated line per message on the separate
// CHAT_TRANSLATED_TOPIC, targeted (destination_identities, server-side)
// so this client only ever receives translations meant for its own
// chat_language.
export default function ChatPanel({ chatLanguage, fetchChatHistory }) {
  const room = useRoomContext()
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const bottomRef = useRef(null)

  // Persisted history, loaded once per meeting (not re-fetched on every
  // chatLanguage change — flipping your reading language mid-call
  // shouldn't re-pull the whole log, just change which translations are
  // still cached against upcoming messages the case for that language
  // wasn't fetched has already been reasoned about server-side).
  useEffect(() => {
    if (!fetchChatHistory) return
    let cancelled = false
    fetchChatHistory()
      .then((history) => {
        if (cancelled) return
        setMessages(
          history.map((m) => ({
            messageId: m.message_id,
            senderIdentity: m.sender_identity,
            originalText: m.original_text,
            sourceLanguage: m.source_language,
            translatedText: m.translations?.[chatLanguage],
            targetLanguage: m.translations?.[chatLanguage] ? chatLanguage : undefined,
          })),
        )
      })
      .catch(() => {
        // Best-effort — an empty/failed history fetch just means the
        // panel starts blank instead of pre-populated; live messages
        // still work.
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchChatHistory])

  useEffect(() => {
    if (!room) return

    const onOriginal = async (reader, participantInfo) => {
      let payload
      try {
        payload = JSON.parse(await reader.readAll())
      } catch {
        return
      }
      if (participantInfo.identity === room.localParticipant.identity) return // own message already appended optimistically on send
      setMessages((prev) => [
        ...prev,
        {
          messageId: payload.message_id,
          senderIdentity: participantInfo.identity,
          originalText: payload.original_text,
          sourceLanguage: payload.source_language,
        },
      ])
    }

    const onTranslated = async (reader) => {
      let payload
      try {
        payload = JSON.parse(await reader.readAll())
      } catch {
        return
      }
      if (payload.target_language !== chatLanguage) return // stale handler registration mid-swap — ignore
      setMessages((prev) =>
        prev.map((m) =>
          m.messageId === payload.message_id
            ? { ...m, translatedText: payload.translated_text, targetLanguage: payload.target_language }
            : m,
        ),
      )
    }

    room.registerTextStreamHandler(CHAT_TOPIC, onOriginal)
    room.registerTextStreamHandler(CHAT_TRANSLATED_TOPIC, onTranslated)
    return () => {
      room.unregisterTextStreamHandler(CHAT_TOPIC)
      room.unregisterTextStreamHandler(CHAT_TRANSLATED_TOPIC)
    }
  }, [room, chatLanguage])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'nearest' })
  }, [messages])

  const handleSend = useCallback(
    async (e) => {
      e.preventDefault()
      const text = draft.trim()
      if (!text || !room) return
      const messageId = crypto.randomUUID()
      setDraft('')
      // Optimistic local append — our own message is never echoed back to
      // us over lk.chat (the relay only ever translates FOR others).
      setMessages((prev) => [
        ...prev,
        { messageId, senderIdentity: room.localParticipant.identity, originalText: text, sourceLanguage: chatLanguage },
      ])
      try {
        await room.localParticipant.sendText(
          JSON.stringify({
            message_id: messageId,
            sender_identity: room.localParticipant.identity,
            original_text: text,
            source_language: chatLanguage,
          }),
          { topic: CHAT_TOPIC },
        )
      } catch {
        // Best-effort — nothing else in the call depends on this succeeding.
      }
    },
    [draft, room, chatLanguage],
  )

  return (
    <div className="cq-chat-panel">
      <div className="cq-chat-messages">
        {messages.length === 0 && <div className="cq-chat-empty">No messages yet.</div>}
        {messages.map((m) => (
          <div key={m.messageId} className="cq-chat-message">
            <div className="cq-chat-message-original">{m.originalText}</div>
            {m.translatedText && m.targetLanguage === chatLanguage && m.sourceLanguage !== chatLanguage && (
              <div className="cq-chat-message-translated">{m.translatedText}</div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      <form className="cq-chat-form" onSubmit={handleSend}>
        <input
          className="cq-chat-input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Type a message…"
          aria-label="Chat message"
        />
        <button type="submit" className="btn btn-primary" disabled={!draft.trim()}>
          Send
        </button>
      </form>
    </div>
  )
}
