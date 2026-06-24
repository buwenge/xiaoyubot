"use client";

import { useState } from "react";
import type { EmotionEvent } from "@/lib/types";
import { IconCheck, IconEdit, IconClose } from "./Icons";

interface EmotionEventItemProps {
  event: EmotionEvent;
  onDismiss: (id: number) => void;
  onEdit: (id: number, updates: Partial<EmotionEvent>) => void;
}

const EMOTION_COLORS: Record<string, string> = {
  // user negative
  "生气": "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300",
  "委屈": "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300",
  "焦虑": "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300",
  "难过": "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
  "害怕": "bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300",
  "烦躁": "bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300",
  "质疑": "bg-stone-100 text-stone-700 dark:bg-stone-900/30 dark:text-stone-300",
  // user positive
  "开心": "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300",
  "感动": "bg-pink-100 text-pink-700 dark:bg-pink-900/30 dark:text-pink-300",
  "兴奋": "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300",
  "甜": "bg-rose-100 text-rose-600 dark:bg-rose-900/30 dark:text-rose-300",
  "心疼正向": "bg-pink-100 text-pink-600 dark:bg-pink-900/30 dark:text-pink-300",
  // user neutral
  "无聊": "bg-gray-100 text-gray-600 dark:bg-gray-900/30 dark:text-gray-300",
  "疲惫": "bg-slate-100 text-slate-600 dark:bg-slate-900/30 dark:text-slate-300",
  "无语": "bg-zinc-100 text-zinc-600 dark:bg-zinc-900/30 dark:text-zinc-300",
  // xiaoyu
  "紧张": "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300",
  "自责": "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300",
  "心疼": "bg-fuchsia-100 text-fuchsia-700 dark:bg-fuchsia-900/30 dark:text-fuchsia-300",
  "撒娇": "bg-pink-100 text-pink-600 dark:bg-pink-900/30 dark:text-pink-300",
};

function getEmotionColor(emotion: string): string {
  return EMOTION_COLORS[emotion] || "bg-warm-accent/10 text-warm-accent";
}

function formatTime(ts: string): string {
  try {
    const d = new Date(ts);
    return `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
  } catch {
    return ts.slice(11, 16);
  }
}

function IntensityDots({ intensity }: { intensity: number }) {
  return (
    <div className="flex gap-0.5">
      {[1, 2, 3, 4, 5].map((i) => (
        <div
          key={i}
          className={`w-1.5 h-1.5 rounded-full ${i <= intensity ? "bg-warm-accent" : "bg-warm-border/30"}`}
        />
      ))}
    </div>
  );
}

export function EmotionEventItem({ event, onDismiss, onEdit }: EmotionEventItemProps) {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editEmotion, setEditEmotion] = useState(event.emotion);
  const [editCause, setEditCause] = useState(event.cause || "");

  const isOpen = event.state === "open";
  const isResolved = event.state === "resolved";
  const isDismissed = event.state === "dismissed";

  const handleSaveEdit = () => {
    onEdit(event.id, { emotion: editEmotion, cause: editCause });
    setEditing(false);
  };

  return (
    <div
      className={`glass rounded-2xl p-3 transition-all ${
        isOpen ? "ring-1 ring-warm-accent/20" : ""
      } ${isResolved || isDismissed ? "opacity-50" : ""}`}
      onClick={() => !editing && setExpanded(!expanded)}
    >
      <div className="flex items-start gap-3">
        {/* Time */}
        <div className="flex flex-col items-center min-w-[40px]">
          <span className="text-xs text-warm-text-secondary/60 font-mono">{formatTime(event.timestamp)}</span>
          <span className="text-[10px] text-warm-text-secondary/40 mt-0.5">
            {event.subject === "user" ? "我" : "小予"}
          </span>
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${getEmotionColor(event.emotion)}`}>
              {event.emotion}
            </span>
            <IntensityDots intensity={event.intensity} />
            {isResolved && <span className="text-[10px] text-emerald-500">已消解</span>}
            {isDismissed && <span className="text-[10px] text-warm-text-secondary/40">已标记</span>}
          </div>
          {event.cause && (
            <p className="text-xs text-warm-text-secondary mt-1 leading-relaxed">{event.cause}</p>
          )}
        </div>
      </div>

      {/* Expanded: source excerpt + actions */}
      {expanded && !editing && (
        <div className="mt-3 pt-3 border-t border-warm-border/20" onClick={(e) => e.stopPropagation()}>
          {event.source_excerpt && (
            <p className="text-xs text-warm-text-secondary/50 italic mb-2 leading-relaxed">
              &ldquo;{event.source_excerpt}&rdquo;
            </p>
          )}
          <div className="flex gap-2">
            {isOpen && (
              <button
                onClick={() => onDismiss(event.id)}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs bg-warm-bg hover:bg-warm-border/20 text-warm-text-secondary transition-colors"
                style={{ minHeight: 36, minWidth: 44 }}
              >
                <IconCheck className="w-3.5 h-3.5" />
                已过去了
              </button>
            )}
            <button
              onClick={() => { setEditing(true); setEditEmotion(event.emotion); setEditCause(event.cause || ""); }}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs bg-warm-bg hover:bg-warm-border/20 text-warm-text-secondary transition-colors"
              style={{ minHeight: 36, minWidth: 44 }}
            >
              <IconEdit className="w-3.5 h-3.5" />
              修改
            </button>
          </div>
        </div>
      )}

      {/* Edit mode */}
      {editing && (
        <div className="mt-3 pt-3 border-t border-warm-border/20 space-y-2" onClick={(e) => e.stopPropagation()}>
          <input
            type="text"
            value={editEmotion}
            onChange={(e) => setEditEmotion(e.target.value)}
            className="w-full px-3 py-2 rounded-lg text-xs bg-warm-bg border border-warm-border/30 text-warm-text"
            placeholder="情绪标签"
          />
          <input
            type="text"
            value={editCause}
            onChange={(e) => setEditCause(e.target.value)}
            className="w-full px-3 py-2 rounded-lg text-xs bg-warm-bg border border-warm-border/30 text-warm-text"
            placeholder="原因"
          />
          <div className="flex gap-2">
            <button
              onClick={handleSaveEdit}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs bg-warm-accent/15 text-warm-accent font-medium"
              style={{ minHeight: 36, minWidth: 44 }}
            >
              <IconCheck className="w-3.5 h-3.5" />
              保存
            </button>
            <button
              onClick={() => setEditing(false)}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs bg-warm-bg text-warm-text-secondary"
              style={{ minHeight: 36, minWidth: 44 }}
            >
              <IconClose className="w-3.5 h-3.5" />
              取消
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
