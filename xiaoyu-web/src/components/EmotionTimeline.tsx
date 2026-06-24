"use client";

import { useMemo } from "react";
import type { EmotionEvent } from "@/lib/types";
import { EmotionEventItem } from "./EmotionEventItem";

interface EmotionTimelineProps {
  events: EmotionEvent[];
  onDismiss: (id: number) => void;
  onEdit: (id: number, updates: Partial<EmotionEvent>) => void;
}

function groupByDate(events: EmotionEvent[]): Map<string, EmotionEvent[]> {
  const map = new Map<string, EmotionEvent[]>();
  for (const ev of events) {
    const date = ev.timestamp.slice(0, 10);
    if (!map.has(date)) map.set(date, []);
    map.get(date)!.push(ev);
  }
  return map;
}

function formatDateLabel(dateStr: string): string {
  const d = new Date(dateStr);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "今天";
  if (d.toDateString() === yesterday.toDateString()) return "昨天";
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export function EmotionTimeline({ events, onDismiss, onEdit }: EmotionTimelineProps) {
  const grouped = useMemo(() => groupByDate(events), [events]);
  const sortedDates = useMemo(() => [...grouped.keys()].sort().reverse(), [grouped]);

  if (events.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-40 text-warm-text-secondary/40">
        <p className="text-sm">最近3天没有情绪记录</p>
      </div>
    );
  }

  return (
    <div className="space-y-4 py-3">
      {sortedDates.map((date) => (
        <div key={date}>
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-medium text-warm-text-secondary/60">{formatDateLabel(date)}</span>
            <div className="flex-1 h-px bg-warm-border/30" />
          </div>
          <div className="space-y-2">
            {grouped.get(date)!.map((ev) => (
              <EmotionEventItem key={ev.id} event={ev} onDismiss={onDismiss} onEdit={onEdit} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
