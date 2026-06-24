"use client";

import { useEffect, useMemo, useState } from "react";
import type { EmotionEvent, EmotionSummary } from "@/lib/types";
import { IconBack } from "./Icons";
import { EmotionTimeline } from "./EmotionTimeline";
import { EmotionSummaryCard } from "./EmotionSummaryCard";

interface EmotionPanelProps {
  events: EmotionEvent[];
  summary: EmotionSummary[];
  loading: boolean;
  onBack: () => void;
  onDismiss: (id: number) => void;
  onEdit: (id: number, updates: Partial<EmotionEvent>) => void;
  onRefresh: () => void;
}

export function EmotionPanel({ events, summary, loading, onBack, onDismiss, onEdit, onRefresh }: EmotionPanelProps) {
  const [tab, setTab] = useState<"timeline" | "summary">("timeline");

  useEffect(() => {
    onRefresh();
  }, [onRefresh]);

  const threeDaysAgo = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() - 3);
    return d.toISOString();
  }, []);

  const recentEvents = useMemo(
    () => events.filter((e) => e.timestamp >= threeDaysAgo),
    [events, threeDaysAgo]
  );

  const olderEvents = useMemo(
    () => events.filter((e) => e.timestamp < threeDaysAgo),
    [events, threeDaysAgo]
  );

  return (
    <div className="h-full flex flex-col bg-warm-bg">
      {/* Header */}
      <div className="bar-blend px-4 pt-[max(0.75rem,env(safe-area-inset-top))] pb-3 flex items-center gap-3">
        <button onClick={onBack} className="p-2 -ml-2 rounded-xl hover:bg-warm-bg/50 md:hidden" style={{ minWidth: 44, minHeight: 44 }}>
          <IconBack className="w-5 h-5" />
        </button>
        <h1 className="text-base font-medium text-warm-text">事件簿</h1>
        <div className="flex-1" />
        <div className="flex gap-1">
          {(["timeline", "summary"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-1.5 rounded-lg text-xs transition-all ${
                tab === t
                  ? "bg-warm-accent/15 text-warm-accent font-medium"
                  : "text-warm-text-secondary/60 hover:text-warm-text-secondary"
              }`}
              style={{ minHeight: 36 }}
            >
              {t === "timeline" ? "时间线" : "汇总"}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 pb-24">
        {loading ? (
          <div className="flex items-center justify-center h-40">
            <div className="w-5 h-5 border-2 border-warm-accent/30 border-t-warm-accent rounded-full animate-spin" />
          </div>
        ) : tab === "timeline" ? (
          <EmotionTimeline events={recentEvents} onDismiss={onDismiss} onEdit={onEdit} />
        ) : (
          <EmotionSummaryCard events={olderEvents} summary={summary} />
        )}
      </div>
    </div>
  );
}
