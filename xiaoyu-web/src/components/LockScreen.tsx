"use client";

import { useState } from "react";

interface LockScreenProps {
  onUnlock: (secret: string) => void;
}

export function LockScreen({ onUnlock }: LockScreenProps) {
  const [input, setInput] = useState("");
  const [shaking, setShaking] = useState(false);

  const handleSubmit = () => {
    if (!input.trim()) {
      setShaking(true);
      setTimeout(() => setShaking(false), 500);
      return;
    }
    onUnlock(input);
  };

  const now = new Date();
  const timeStr = now.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
  const dateStr = now.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" });

  return (
    <div className="h-full flex flex-col items-center justify-between relative overflow-hidden">
      <div
        className="absolute inset-0 bg-cover bg-center bg-no-repeat"
        style={{ backgroundImage: "url('/bg-desktop.png')" }}
      />
      <div className="absolute inset-0 bg-black/10" />

      <div className="relative z-10 pt-16 text-center animate-fade-in">
        <div className="text-5xl font-light text-white tracking-wide" style={{ textShadow: "0 1px 8px rgba(0,0,0,0.3)" }}>
          {timeStr}
        </div>
        <div className="text-sm text-white/80 mt-2" style={{ textShadow: "0 1px 4px rgba(0,0,0,0.3)" }}>
          {dateStr}
        </div>
      </div>

      <div className={`relative z-10 mb-20 w-64 animate-slide-up ${shaking ? "animate-[shake_0.5s_ease-in-out]" : ""}`}>
        <style jsx>{`
          @keyframes shake {
            0%, 100% { transform: translateX(0); }
            25% { transform: translateX(-8px); }
            75% { transform: translateX(8px); }
          }
        `}</style>
        <div className="glass rounded-2xl p-5">
          <p className="text-center text-sm text-warm-text/70 mb-4 font-light">
            向上滑动解锁
          </p>
          <input
            type="password"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
            className="w-full px-4 py-2.5 rounded-xl bg-white/20 dark:bg-black/20 border border-white/20 text-warm-text text-center text-sm placeholder:text-warm-text-secondary/50 focus:outline-none focus:border-warm-accent/50 transition-all"
            placeholder="..."
            autoFocus
          />
          <button
            onClick={handleSubmit}
            className="w-full mt-3 py-2.5 rounded-xl bg-warm-accent/80 text-white text-sm font-medium hover:bg-warm-accent transition-colors"
          >
            解锁
          </button>
        </div>
      </div>
    </div>
  );
}
