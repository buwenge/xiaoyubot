"use client";

import { useState } from "react";
import type { LogEntry, StatusData } from "@/lib/types";
import { StatusPanel } from "./StatusPanel";
import { LogPanel } from "./LogPanel";
import { SettingsPanel } from "./SettingsPanel";
import { IconBack } from "./Icons";

type Tab = "status" | "logs" | "settings";

const TABS: { key: Tab; label: string }[] = [
  { key: "status", label: "状态" },
  { key: "logs", label: "日志" },
  { key: "settings", label: "设置" },
];

interface SettingsAppProps {
  status: StatusData | null;
  logs: LogEntry[];
  onRequestLogs: (filter: string, limit: number) => void;
  onSetForgeThreshold: (value: number) => void;
  onSetSonnetForgeThreshold: (value: number) => void;
  onSetRetainTokens: (value: number) => void;
  onSetSonnetRetainTokens: (value: number) => void;
  onSetGroupMaxRounds: (value: number) => void;
  onForge: (target: "xiaoyu" | "sonnet") => void;
  onBack: () => void;
  onRefreshStatus: () => void;
}

export function SettingsApp({
  status, logs, onRequestLogs, onSetForgeThreshold, onSetSonnetForgeThreshold,
  onSetRetainTokens, onSetSonnetRetainTokens, onSetGroupMaxRounds, onForge, onBack, onRefreshStatus,
}: SettingsAppProps) {
  const [activeTab, setActiveTab] = useState<Tab>("status");

  return (
    <div className="h-full flex flex-col relative overflow-hidden">
      <div className="absolute inset-0 bg-cover bg-center bg-no-repeat md:hidden" style={{ backgroundImage: "url('/bg-desktop.png')" }} />
      <div className="absolute inset-0 bg-cover bg-center bg-no-repeat hidden md:block" style={{ backgroundImage: "url('/bg-desktop-pc.png')" }} />
      <div className="absolute inset-0 bg-warm-bg/60 dark:bg-[#1E1814]/60 backdrop-blur-sm" />

      <div className="relative z-10 flex flex-col h-full">
        {/* Header */}
        <div className="bar-blend px-3 py-2.5 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <button
              onClick={onBack}
              className="p-1.5 rounded-lg text-warm-text-secondary hover:text-warm-text transition-colors"
            >
              <IconBack className="w-5 h-5" />
            </button>
            <span className="text-sm font-medium text-warm-text">管理</span>
          </div>
          <div className="w-8" />
        </div>

        {/* Tab bar */}
        <div className="glass mx-3 mt-2 rounded-xl flex p-1">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex-1 py-1.5 rounded-lg text-xs transition-all ${
                activeTab === tab.key
                  ? "bg-warm-accent/15 text-warm-accent font-medium"
                  : "text-warm-text-secondary/60 hover:text-warm-text-secondary"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto mx-3 md:mx-auto md:w-full md:max-w-xl mt-2 mb-16 md:mb-3 glass rounded-2xl">
          {activeTab === "status" && <StatusPanel status={status} onRefresh={onRefreshStatus} />}
          {activeTab === "logs" && <LogPanel logs={logs} onRequestLogs={onRequestLogs} />}
          {activeTab === "settings" && (
            <SettingsPanel
              status={status}
              onSetForgeThreshold={onSetForgeThreshold}
              onSetSonnetForgeThreshold={onSetSonnetForgeThreshold}
              onSetRetainTokens={onSetRetainTokens}
              onSetSonnetRetainTokens={onSetSonnetRetainTokens}
              onSetGroupMaxRounds={onSetGroupMaxRounds}
              onForge={onForge}
            />
          )}
        </div>
      </div>
    </div>
  );
}
