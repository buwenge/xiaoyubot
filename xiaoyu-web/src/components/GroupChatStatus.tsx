"use client";

import type { GroupAutoStatus } from "@/lib/types";

interface GroupChatStatusProps {
  status: GroupAutoStatus;
  onPause: () => void;
}

export function GroupChatStatus({ status, onPause }: GroupChatStatusProps) {
  if (!status.active) return null;

  return (
    <div className="glass mx-3 mt-2 rounded-xl flex items-center justify-center gap-3 px-4 py-2 text-sm">
      <span className="w-1.5 h-1.5 rounded-full bg-warm-accent animate-gentle-pulse" />
      <span className="text-warm-text-secondary text-xs">
        自动对话中（第 {status.round}/{status.max_rounds} 轮）
      </span>
      <button
        onClick={onPause}
        className="px-3 py-1 rounded-lg text-[11px] bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
      >
        暂停
      </button>
    </div>
  );
}
