"use client";

import { useMemo } from "react";
import type { EmotionEvent, EmotionSummary } from "@/lib/types";

interface EmotionSummaryCardProps {
  events: EmotionEvent[];
  summary: EmotionSummary[];
}

function groupByWeek(events: EmotionEvent[]): Map<string, EmotionEvent[]> {
  const map = new Map<string, EmotionEvent[]>();
  for (const ev of events) {
    const d = new Date(ev.timestamp);
    const weekStart = new Date(d);
    weekStart.setDate(d.getDate() - d.getDay());
    const key = weekStart.toISOString().slice(0, 10);
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(ev);
  }
  return map;
}

function formatWeekLabel(weekStart: string): string {
  const start = new Date(weekStart);
  const end = new Date(start);
  end.setDate(start.getDate() + 6);
  return `${start.getMonth() + 1}/${start.getDate()} - ${end.getMonth() + 1}/${end.getDate()}`;
}

function summarizeWeek(events: EmotionEvent[]): { user: Map<string, number>; xiaoyu: Map<string, number> } {
  const user = new Map<string, number>();
  const xiaoyu = new Map<string, number>();
  for (const ev of events) {
    const map = ev.subject === "user" ? user : xiaoyu;
    map.set(ev.emotion, (map.get(ev.emotion) || 0) + 1);
  }
  return { user, xiaoyu };
}

function EmotionBar({ emotion, count, maxCount }: { emotion: string; count: number; maxCount: number }) {
  const width = Math.max(20, (count / maxCount) * 100);
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-14 text-right text-warm-text-secondary/60 shrink-0">{emotion}</span>
      <div className="flex-1 h-4 bg-warm-border/10 rounded-full overflow-hidden">
        <div
          className="h-full bg-warm-accent/30 rounded-full transition-all"
          style={{ width: `${width}%` }}
        />
      </div>
      <span className="w-6 text-warm-text-secondary/50 text-right">{count}</span>
    </div>
  );
}

export function EmotionSummaryCard({ events, summary }: EmotionSummaryCardProps) {
  const weeks = useMemo(() => groupByWeek(events), [events]);
  const sortedWeeks = useMemo(() => [...weeks.keys()].sort().reverse(), [weeks]);

  if (events.length === 0 && summary.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-40 text-warm-text-secondary/40">
        <p className="text-sm">暂无更早的情绪记录</p>
      </div>
    );
  }

  // global summary card
  const userSummary = summary.filter((s) => s.subject === "user").sort((a, b) => b.count - a.count);
  const xiaoyuSummary = summary.filter((s) => s.subject === "xiaoyu").sort((a, b) => b.count - a.count);
  const maxCount = Math.max(...summary.map((s) => s.count), 1);

  return (
    <div className="space-y-4 py-3">
      {/* Overall summary */}
      {summary.length > 0 && (
        <div className="glass rounded-2xl p-4 space-y-3">
          <h3 className="text-xs font-medium text-warm-text-secondary/60">近30天总览</h3>
          {userSummary.length > 0 && (
            <div>
              <p className="text-[10px] text-warm-text-secondary/40 mb-1.5">我的情绪</p>
              <div className="space-y-1">
                {userSummary.map((s) => (
                  <EmotionBar key={s.emotion} emotion={s.emotion} count={s.count} maxCount={maxCount} />
                ))}
              </div>
            </div>
          )}
          {xiaoyuSummary.length > 0 && (
            <div>
              <p className="text-[10px] text-warm-text-secondary/40 mb-1.5">小予的情绪</p>
              <div className="space-y-1">
                {xiaoyuSummary.map((s) => (
                  <EmotionBar key={s.emotion} emotion={s.emotion} count={s.count} maxCount={maxCount} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Weekly cards */}
      {sortedWeeks.map((week) => {
        const weekEvents = weeks.get(week)!;
        const { user, xiaoyu } = summarizeWeek(weekEvents);
        const weekMax = Math.max(...[...user.values(), ...xiaoyu.values()], 1);
        return (
          <div key={week} className="glass rounded-2xl p-4 space-y-2">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-medium text-warm-text-secondary/60">{formatWeekLabel(week)}</h3>
              <span className="text-[10px] text-warm-text-secondary/40">{weekEvents.length} 条</span>
            </div>
            {user.size > 0 && (
              <div className="space-y-1">
                {[...user.entries()].sort((a, b) => b[1] - a[1]).map(([emo, cnt]) => (
                  <EmotionBar key={emo} emotion={emo} count={cnt} maxCount={weekMax} />
                ))}
              </div>
            )}
            {xiaoyu.size > 0 && (
              <div className="mt-2 pt-2 border-t border-warm-border/10 space-y-1">
                <p className="text-[10px] text-warm-text-secondary/30">小予</p>
                {[...xiaoyu.entries()].sort((a, b) => b[1] - a[1]).map(([emo, cnt]) => (
                  <EmotionBar key={emo} emotion={emo} count={cnt} maxCount={weekMax} />
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
