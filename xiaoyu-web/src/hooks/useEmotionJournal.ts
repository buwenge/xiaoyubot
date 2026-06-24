"use client";

import { useCallback, useState } from "react";
import type { EmotionEvent, EmotionSummary, WsDownMessage } from "@/lib/types";

export function useEmotionJournal() {
  const [events, setEvents] = useState<EmotionEvent[]>([]);
  const [summary, setSummary] = useState<EmotionSummary[]>([]);
  const [loading, setLoading] = useState(false);

  const handleWsMessage = useCallback((msg: WsDownMessage) => {
    if (msg.type === "emotion_events") {
      const m = msg as { events: EmotionEvent[]; summary: EmotionSummary[] };
      setEvents(m.events);
      setSummary(m.summary);
      setLoading(false);
    } else if (msg.type === "emotion_events_new") {
      const m = msg as { events: EmotionEvent[] };
      setEvents((prev) => [...m.events, ...prev]);
    } else if (msg.type === "emotion_event_updated") {
      const m = msg as { id: number; state?: string; emotion?: string; intensity?: number; cause?: string };
      setEvents((prev) =>
        prev.map((ev) =>
          ev.id === m.id
            ? {
                ...ev,
                ...(m.state && { state: m.state as EmotionEvent["state"] }),
                ...(m.emotion && { emotion: m.emotion }),
                ...(m.intensity && { intensity: m.intensity }),
                ...(m.cause && { cause: m.cause }),
              }
            : ev
        )
      );
    }
  }, []);

  const requestEvents = useCallback((send: (msg: Record<string, unknown>) => void, days = 30) => {
    setLoading(true);
    send({ type: "get_emotion_events", days });
  }, []);

  const dismissEvent = useCallback((send: (msg: Record<string, unknown>) => void, id: number) => {
    send({ type: "emotion_dismiss", id });
  }, []);

  const editEvent = useCallback((send: (msg: Record<string, unknown>) => void, id: number, updates: Partial<EmotionEvent>) => {
    send({ type: "emotion_edit", id, updates });
  }, []);

  return { events, summary, loading, handleWsMessage, requestEvents, dismissEvent, editEvent };
}
