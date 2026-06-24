"use client";

import { IconHome, IconChat, IconHeart, IconSettings } from "./Icons";

export type DockScreen = "home" | "chat" | "emotions" | "settings";

interface DockBarProps {
  active: DockScreen;
  onChange: (screen: DockScreen) => void;
  hasChatActivity?: boolean;
}

const ITEMS: { key: DockScreen; label: string; icon: (cls: string) => React.ReactNode }[] = [
  { key: "home", label: "桌面", icon: (cls) => <IconHome className={cls} /> },
  { key: "chat", label: "聊天", icon: (cls) => <IconChat className={cls} /> },
  { key: "emotions", label: "事件簿", icon: (cls) => <IconHeart className={cls} /> },
  { key: "settings", label: "设置", icon: (cls) => <IconSettings className={cls} /> },
];

export function DockBar({ active, onChange, hasChatActivity }: DockBarProps) {
  return (
    <div className="bar-blend px-2 py-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] flex items-center justify-around md:hidden">
      {ITEMS.map((item) => {
        const isActive = active === item.key;
        return (
          <button
            key={item.key}
            onClick={() => onChange(item.key)}
            className={`relative flex flex-col items-center gap-0.5 px-5 py-1.5 rounded-xl transition-all ${
              isActive
                ? "text-warm-accent"
                : "text-warm-text-secondary/60 hover:text-warm-text-secondary"
            }`}
          >
            {item.icon(isActive ? "w-5 h-5" : "w-5 h-5")}
            <span className="text-[10px] font-light">{item.label}</span>
            {item.key === "chat" && hasChatActivity && !isActive && (
              <span className="absolute top-1 right-3 w-1.5 h-1.5 rounded-full bg-warm-accent animate-gentle-pulse" />
            )}
          </button>
        );
      })}
    </div>
  );
}
