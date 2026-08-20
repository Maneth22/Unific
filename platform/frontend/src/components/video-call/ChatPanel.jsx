import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useParticipants, useRoomContext } from '@livekit/components-react'
import { CHAT_TOPIC, CHAT_TRANSLATED_TOPIC } from './callConstants'

// How long to hold a just-arrived original message off-screen waiting for
// its translation before showing it untranslated anyway — long enough for
// the one Gemini call chat_relay.py makes per distinct target language,
// short enough that a slow/failed translation doesn't make the message
// look lost. Untranslated-but-present still beats never appearing at all.
const TRANSLATION_WAIT_MS = 4000

function formatTimestamp(ts) {
  if (!ts) return ''
  return new Date(ts).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

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
//
// Every message carries a `translations` map ({lang: text}) rather than a
// single baked-in translatedText/targetLanguage pair — the same shape the
// persisted-history payload already uses — so switching chat_language mid-
// call re-derives what to show from data already held, live or historical
// alike, instead of two divergent code paths.
//
// A message whose translation is still expected (cross-language, not yet
// arrived) is held in `pendingRef` rather than appended right away, so the
// original text and its translation land in the message list — and so on
// screen — together, not as a visible "pop in a beat later" update.
export default function ChatPanel({ chatLanguage, fetchChatHistory }) {
  const room = useRoomContext()
  const participants = useParticipants()
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const bottomRef = useRef(null)
  const pendingRef = useRef(new Map()) // messageId -> { entry, timer }

  const participantsRef = useRef(participants)
  useEffect(() => {
    participantsRef.current = participants
  }, [participants])

  function resolveName(identity) {
    return participantsRef.current.find((p) => p.identity === identity)?.name || identity
  }

  // Persisted history, loaded once per meeting (not re-fetched on every
  // chatLanguage change — flipping your reading language mid-call just
  // changes which cached translation is picked out of each message's own
  // `translations` map at render time, see the JSX below).
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
            translations: m.translations || {},
            timestamp: m.created_at ? new Date(m.created_at).getTime() : null,
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

    const flushPending = (messageId, extra) => {
      const pending = pendingRef.current.get(messageId)
      if (!pending) return false
      clearTimeout(pending.timer)
      pendingRef.current.delete(messageId)
      setMessages((prev) => [...prev, { ...pending.entry, ...extra }])
      return true
    }

    const onOriginal = async (reader, participantInfo) => {
      let payload
      try {
        payload = JSON.parse(await reader.readAll())
      } catch {
        return
      }
      if (participantInfo.identity === room.localParticipant.identity) return // own message already appended optimistically on send

      const entry = {
        messageId: payload.message_id,
        senderIdentity: participantInfo.identity,
        originalText: payload.original_text,
        sourceLanguage: payload.source_language,
        translations: {},
        timestamp: payload.timestamp ? payload.timestamp * 1000 : Date.now(),
      }

      // Same language as what I read chat in — chat_relay.py never
      // computes (or sends) a translation for this case at all, so there
      // is nothing to wait for; show it immediately.
      if (payload.source_language === chatLanguage) {
        setMessages((prev) => [...prev, entry])
        return
      }

      // Otherwise hold it until its translation arrives (or the wait
      // elapses) so the bubble appears complete — original and
      // translation together — rather than the translation flashing in
      // afterward.
      const timer = setTimeout(() => flushPending(entry.messageId), TRANSLATION_WAIT_MS)
      pendingRef.current.set(entry.messageId, { entry, timer })
    }

    const onTranslated = async (reader) => {
      let payload
      try {
        payload = JSON.parse(await reader.readAll())
      } catch {
        return
      }
      if (payload.target_language !== chatLanguage) return // stale handler registration mid-swap — ignore

      const translations = { [payload.target_language]: payload.translated_text }
      if (flushPending(payload.message_id, { translations })) return

      // No longer pending — either its wait already elapsed (untranslated
      // version already visible) or it's a historical message; merge the
      // translation into it wherever it already lives instead of dropping it.
      setMessages((prev) =>
        prev.map((m) =>
          m.messageId === payload.message_id
            ? { ...m, translations: { ...m.translations, ...translations } }
            : m,
        ),
      )
    }

    room.registerTextStreamHandler(CHAT_TOPIC, onOriginal)
    room.registerTextStreamHandler(CHAT_TRANSLATED_TOPIC, onTranslated)
    return () => {
      room.unregisterTextStreamHandler(CHAT_TOPIC)
      room.unregisterTextStreamHandler(CHAT_TRANSLATED_TOPIC)
      for (const { timer } of pendingRef.current.values()) clearTimeout(timer)
      pendingRef.current.clear()
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
      const timestamp = Date.now()
      setDraft('')
      // Optimistic local append — our own message is never echoed back to
      // us over lk.chat (the relay only ever translates FOR others).
      setMessages((prev) => [
        ...prev,
        {
          messageId, senderIdentity: room.localParticipant.identity, originalText: text,
          sourceLanguage: chatLanguage, translations: {}, timestamp,
        },
      ])
      try {
        await room.localParticipant.sendText(
          JSON.stringify({
            message_id: messageId,
            sender_identity: room.localParticipant.identity,
            original_text: text,
            source_language: chatLanguage,
            timestamp: timestamp / 1000,
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
        {messages.map((m) => {
          const isOwn = room && m.senderIdentity === room.localParticipant.identity
          const translated = m.translations?.[chatLanguage]
          const showTranslation = translated && m.sourceLanguage !== chatLanguage
          return (
            <div key={m.messageId} className={`cq-chat-message-row ${isOwn ? 'cq-chat-message-row-own' : ''}`}>
              <div className={`cq-chat-message ${isOwn ? 'cq-chat-message-own' : 'cq-chat-message-other'}`}>
                {!isOwn && <div className="cq-chat-message-sender">{resolveName(m.senderIdentity)}</div>}
                <div className="cq-chat-message-original">{m.originalText}</div>
                {showTranslation && <div className="cq-chat-message-translated">{translated}</div>}
                <div className="cq-chat-message-time">{formatTimestamp(m.timestamp)}</div>
              </div>
            </div>
          )
        })}
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
