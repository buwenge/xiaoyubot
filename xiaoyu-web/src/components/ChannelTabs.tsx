"use client";

import type { Channel } from "@/lib/types";

const TABS: { key: Channel; label: string }[] = [
  { key: "xiaoyu", label: "小予" },
  { key: "group", label: "群聊" },
  { key: "sonnet", label: "Sonnet" },
];

interface ChannelTabsProps {
  active: Channel;
  onChange: (ch: Channel) => void;
  streamingChannels: Set<Channel>;
}

export function ChannelTabs({ active, onChange, streamingChannels }: ChannelTabsProps) {
  return (
    <div className="flex gap-0.5 flex-1">
      {TABS.map((tab) => (
        <button
          key={tab.key}
          onClick={() => onChange(tab.key)}
          className={`relative px-3 py-1.5 rounded-lg text-sm transition-all ${
            active === tab.key
              ? "text-warm-accent font-medium"
              : "text-warm-text-secondary/60 hover:text-warm-text-secondary"
          }`}
        >
          {tab.label}
          {active === tab.key && (
            <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-4 h-0.5 rounded-full bg-warm-accent" />
          )}
          {streamingChannels.has(tab.key) && active !== tab.key && (
            <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 bg-warm-accent rounded-full animate-gentle-pulse" />
          )}
        </button>
      ))}
    </div>
  );
}
