"use client";

import { useEffect, useRef, useState } from "react";
import type { LogEntry } from "@/lib/types";

const FILTERS = [
  { key: "all", label: "全部" },
  { key: "wake", label: "唤醒" },
  { key: "activity", label: "活动" },
  { key: "message", label: "消息" },
  { key: "error", label: "错误" },
] as const;

const CATEGORY_DOTS: Record<string, string> = {
  wake: "bg-amber-400",
  activity: "bg-blue-400",
  message: "bg-green-400",
  error: "bg-red-400",
};

interface LogPanelProps {
  logs: LogEntry[];
  onRequestLogs: (filter: string, limit: number) => void;
}

export function LogPanel({ logs, onRequestLogs }: LogPanelProps) {
  const [filter, setFilter] = useState("all");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    onRequestLogs(filter, 100);
  }, [filter, onRequestLogs]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  const filtered = filter === "all" ? logs : logs.filter((l) => l.category === filter);

  return (
    <div className="flex flex-col h-full">
      <div className="flex gap-1 p-3 border-b border-warm-border/20">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`px-2.5 py-1 rounded-lg text-[11px] transition-all ${
              filter === f.key
                ? "bg-warm-accent/15 text-warm-accent font-medium"
                : "text-warm-text-secondary/50 hover:text-warm-text-secondary/70"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {filtered.length === 0 ? (
          <div className="p-5 text-sm text-warm-text-secondary/40 text-center font-light">暂无日志</div>
        ) : (
          <div className="divide-y divide-warm-border/10">
            {filtered.map((log, i) => {
              const time = new Date(log.timestamp).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
              const dotColor = CATEGORY_DOTS[log.category] || "bg-warm-text-secondary/30";
              const isError = log.level === "error" || log.category === "error";

              return (
                <div key={`${log.timestamp}-${i}`} className="px-4 py-2.5 text-xs">
                  <div className="flex items-start gap-2.5">
                    <span className="text-warm-text-secondary/40 tabular-nums shrink-0 text-[11px]">{time}</span>
                    <span className={`w-1.5 h-1.5 rounded-full ${dotColor} mt-1.5 shrink-0`} />
                    <span className={`${isError ? "text-red-400" : "text-warm-text/70"} leading-relaxed font-light`}>
                      {log.message}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
