"use client";

import type { StatusData } from "@/lib/types";
import { IconRefresh } from "./Icons";

interface StatusPanelProps {
  status: StatusData | null;
  onRefresh?: () => void;
}

function ProgressBar({ label, pct, sub }: { label: string; pct: number; sub?: string }) {
  const clamped = Math.min(Math.max(pct, 0), 100);
  const color = clamped > 80 ? "bg-red-400" : clamped > 60 ? "bg-amber-400" : "bg-warm-accent";

  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs">
        <span className="text-warm-text-secondary/70">{label}</span>
        <span className="text-warm-text tabular-nums">{Math.round(clamped)}%</span>
      </div>
      <div className="w-full h-1.5 bg-warm-border/30 rounded-full overflow-hidden">
        <div
          className={`h-full ${color} rounded-full transition-all duration-700 ease-out`}
          style={{ width: `${clamped}%` }}
        />
      </div>
      {sub && <div className="text-[11px] text-warm-text-secondary/50 font-light">{sub}</div>}
    </div>
  );
}

function ContextBlock({ label, labelColor, value, max, sessionId }: {
  label: string; labelColor: string; value: number; max: number; sessionId?: string;
}) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  const copyId = (s: string) => navigator.clipboard.writeText(s);

  return (
    <div className="space-y-2">
      <div className={`text-xs font-medium ${labelColor}`}>{label}</div>
      <ProgressBar
        label="上下文"
        pct={pct}
        sub={`${value.toLocaleString()} / ${max.toLocaleString()} tokens`}
      />
      {sessionId && (
        <div className="text-[11px] text-warm-text-secondary/40 font-light">
          session{" "}
          <span
            className="font-mono cursor-pointer hover:text-warm-accent transition-colors"
            onClick={() => copyId(sessionId)}
          >
            {sessionId.slice(0, 8)}
          </span>
        </div>
      )}
    </div>
  );
}

export function StatusPanel({ status, onRefresh }: StatusPanelProps) {
  if (!status) {
    return (
      <div className="p-5 text-sm text-warm-text-secondary/50 text-center font-light">
        等待连接...
      </div>
    );
  }

  const totalInput = status.total_input || 0;
  const threshold = status.forge_threshold || 180000;
  const sonnetInput = status.sonnet_total_input || 0;
  const cost = status.cost_session_total || 0;
  const nextWake = status.next_wake
    ? new Date(status.next_wake).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })
    : "--:--";
  const nextWakeDelta = status.next_wake
    ? Math.max(0, Math.round((new Date(status.next_wake).getTime() - Date.now()) / 60000))
    : null;

  return (
    <div className="p-5 space-y-6 text-sm">
      <div className="flex items-center justify-between">
        <span className="text-xs text-warm-text-secondary/50 font-light">运行状态</span>
        {onRefresh && (
          <button onClick={onRefresh} className="text-warm-text-secondary/40 hover:text-warm-accent transition-colors">
            <IconRefresh className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      <ContextBlock
        label="小予 (Opus)"
        labelColor="text-warm-accent"
        value={totalInput}
        max={threshold}
        sessionId={status.session_id}
      />

      <ContextBlock
        label="Sonnet"
        labelColor="text-[#6B8CAE]"
        value={sonnetInput}
        max={200000}
        sessionId={status.sonnet_session_id}
      />

      <div className="pt-2 border-t border-warm-border/20 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs text-warm-text-secondary/50 font-light">累计费用</span>
          <span className="text-warm-text tabular-nums">${cost.toFixed(2)}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs text-warm-text-secondary/50 font-light">下次唤醒</span>
          <span className="text-warm-text">
            {nextWake}
            {nextWakeDelta !== null && (
              <span className="text-warm-text-secondary/40 text-xs ml-1">({nextWakeDelta}m)</span>
            )}
          </span>
        </div>
      </div>
    </div>
  );
}
