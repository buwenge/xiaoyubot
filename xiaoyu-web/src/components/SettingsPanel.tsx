"use client";

import { useEffect, useRef, useState } from "react";
import type { StatusData } from "@/lib/types";
import { IconChevron } from "./Icons";

interface SettingsPanelProps {
  status: StatusData | null;
  onSetForgeThreshold: (value: number) => void;
  onSetSonnetForgeThreshold: (value: number) => void;
  onSetRetainTokens: (value: number) => void;
  onSetSonnetRetainTokens: (value: number) => void;
  onSetGroupMaxRounds: (value: number) => void;
  onForge: (target: "xiaoyu" | "sonnet") => void;
}

function NumberSetting({
  label, value, min, max, step, suffix, onChange,
}: {
  label: string; value: number; min: number; max: number; step: number;
  suffix?: string; onChange: (v: number) => void;
}) {
  const [local, setLocal] = useState(String(value));
  const [saved, setSaved] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => { setLocal(String(value)); }, [value]);

  const commit = () => {
    const num = Number(local);
    if (isNaN(num) || num < min || num > max) {
      setLocal(String(value));
      return;
    }
    const rounded = Math.round(num / step) * step;
    if (rounded !== value) {
      onChange(rounded);
      setLocal(String(rounded));
      setSaved(true);
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      timeoutRef.current = setTimeout(() => setSaved(false), 1500);
    } else {
      setLocal(String(value));
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      (e.target as HTMLInputElement).blur();
    }
  };

  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-warm-text-secondary/60 font-light">{label}</span>
      <div className="flex items-center gap-1.5">
        <input
          type="text"
          inputMode="numeric"
          value={local}
          onChange={(e) => setLocal(e.target.value)}
          onBlur={commit}
          onKeyDown={handleKeyDown}
          className="w-20 text-right text-xs text-warm-text bg-warm-border/20 rounded-lg px-2.5 py-1.5 outline-none focus:ring-1 focus:ring-warm-accent/30 tabular-nums"
        />
        {suffix && <span className="text-[11px] text-warm-text-secondary/40">{suffix}</span>}
        {saved && <span className="text-[#7B8E6E] text-[11px]">ok</span>}
      </div>
    </div>
  );
}

function ForgeButton({
  label, labelColor, currentTokens, maxTokens, sessionId, onForge,
}: {
  label: string; labelColor: string; currentTokens: number; maxTokens: number;
  sessionId?: string; onForge: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const pct = maxTokens > 0 ? Math.round((currentTokens / maxTokens) * 100) : 0;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div>
          <span className={`text-xs font-medium ${labelColor}`}>{label}</span>
          {sessionId && (
            <span className="text-[11px] text-warm-text-secondary/30 ml-2 font-mono">
              {sessionId.slice(0, 8)}
            </span>
          )}
        </div>
        <span className="text-xs text-warm-text-secondary/50 tabular-nums">
          {currentTokens.toLocaleString()} tokens ({pct}%)
        </span>
      </div>

      {!confirming ? (
        <button
          onClick={() => setConfirming(true)}
          disabled={!sessionId}
          className="w-full py-2 rounded-xl glass-light text-xs text-warm-text-secondary/70 hover:text-warm-accent disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          手动 Forge
        </button>
      ) : (
        <div className="glass-light rounded-xl p-3 space-y-2.5">
          <div className="text-xs text-warm-text-secondary/70 text-center">
            将清除当前上下文并保留尾部记忆，确定？
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setConfirming(false)}
              className="flex-1 py-1.5 rounded-lg text-xs text-warm-text-secondary/60 hover:text-warm-text transition-colors glass-light"
            >
              取消
            </button>
            <button
              onClick={() => { onForge(); setConfirming(false); }}
              className="flex-1 py-1.5 rounded-lg text-xs text-white bg-red-400/80 hover:bg-red-400 transition-colors"
            >
              确认 Forge
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function SettingsPanel({
  status, onSetForgeThreshold, onSetSonnetForgeThreshold,
  onSetRetainTokens, onSetSonnetRetainTokens, onSetGroupMaxRounds, onForge,
}: SettingsPanelProps) {
  const forgeThreshold = status?.forge_threshold || 180000;
  const sonnetForgeThreshold = status?.sonnet_forge_threshold || 180000;
  const retainTokens = status?.retain_tokens || 15000;
  const sonnetRetainTokens = status?.sonnet_retain_tokens || 15000;
  const groupMaxRounds = status?.group_max_rounds || 10;

  return (
    <div className="p-5 space-y-6 text-sm">
      {/* Forge 操作 */}
      <div className="space-y-4">
        <div className="text-xs text-warm-text-secondary/40 font-light">上下文管理</div>
        <ForgeButton
          label="小予 (Opus)"
          labelColor="text-warm-accent"
          currentTokens={status?.total_input || 0}
          maxTokens={forgeThreshold}
          sessionId={status?.session_id}
          onForge={() => onForge("xiaoyu")}
        />
        <ForgeButton
          label="Sonnet"
          labelColor="text-[#6B8CAE]"
          currentTokens={status?.sonnet_total_input || 0}
          maxTokens={sonnetForgeThreshold}
          sessionId={status?.sonnet_session_id}
          onForge={() => onForge("sonnet")}
        />
      </div>

      {/* 参数调整 */}
      <div className="pt-3 border-t border-warm-border/20 space-y-4">
        <div className="text-xs text-warm-text-secondary/40 font-light">小予 (Opus)</div>
        <NumberSetting
          label="Forge 阈值"
          value={forgeThreshold}
          min={100000} max={200000} step={5000}
          onChange={onSetForgeThreshold}
        />
        <NumberSetting
          label="Forge 保留"
          value={retainTokens}
          min={5000} max={100000} step={1000}
          onChange={onSetRetainTokens}
        />
      </div>

      <div className="pt-3 border-t border-warm-border/20 space-y-4">
        <div className="text-xs text-warm-text-secondary/40 font-light">Sonnet</div>
        <NumberSetting
          label="Forge 阈值"
          value={sonnetForgeThreshold}
          min={100000} max={200000} step={5000}
          onChange={onSetSonnetForgeThreshold}
        />
        <NumberSetting
          label="Forge 保留"
          value={sonnetRetainTokens}
          min={5000} max={100000} step={1000}
          onChange={onSetSonnetRetainTokens}
        />
      </div>

      <div className="pt-3 border-t border-warm-border/20 space-y-4">
        <div className="text-xs text-warm-text-secondary/40 font-light">群聊</div>
        <NumberSetting
          label="最大轮次"
          value={groupMaxRounds}
          min={3} max={30} step={1}
          onChange={onSetGroupMaxRounds}
        />
      </div>

      {/* 快捷链接 */}
      <div className="pt-3 border-t border-warm-border/20 space-y-2">
        <div className="text-xs text-warm-text-secondary/40 font-light mb-3">快捷链接</div>
        <a
          href="https://xiao-wo-brain.zeabur.app"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center justify-between px-4 py-3 rounded-xl glass-light text-xs text-warm-text hover:text-warm-accent transition-colors"
        >
          <span>记忆库 (Zeabur)</span>
          <IconChevron className="w-3 h-3 text-warm-text-secondary/30" />
        </a>
      </div>
    </div>
  );
}
