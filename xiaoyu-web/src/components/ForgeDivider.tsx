"use client";

interface ForgeDividerProps {
  timestamp?: string;
  label?: string;
}

export function ForgeDivider({ timestamp, label }: ForgeDividerProps) {
  const timeStr = timestamp
    ? new Date(timestamp).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })
    : "";

  return (
    <div className="flex items-center gap-3 py-2">
      <div className="flex-1 border-t border-dashed border-warm-accent/20" />
      <span className="text-[11px] text-warm-text-secondary/50 whitespace-nowrap font-light">
        {label ? `${label} · ` : ""}上下文已滑动{timeStr && ` · ${timeStr}`}
      </span>
      <div className="flex-1 border-t border-dashed border-warm-accent/20" />
    </div>
  );
}
