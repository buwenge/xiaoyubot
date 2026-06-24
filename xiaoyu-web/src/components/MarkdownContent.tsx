"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneLight, oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { memo, useCallback, useEffect, useState } from "react";

function CopyIcon({ copied }: { copied: boolean }) {
  if (copied) {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="20 6 9 17 4 12" />
      </svg>
    );
  }
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  );
}

function copyText(text: string): Promise<void> {
  if (navigator.clipboard) {
    return navigator.clipboard.writeText(text);
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.cssText = "position:fixed;opacity:0";
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  document.body.removeChild(ta);
  return Promise.resolve();
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(() => {
    copyText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [text]);
  return (
    <button
      onPointerDown={(e) => e.stopPropagation()}
      onClick={handleCopy}
      className={`absolute top-1 right-1 w-8 h-8 flex items-center justify-center rounded-md text-warm-text-secondary/40 hover:text-warm-text-secondary/70 active:text-warm-text-secondary/70 transition-all duration-150 touch-manipulation ${copied ? "scale-90 opacity-60" : ""}`}
    >
      <CopyIcon copied={copied} />
    </button>
  );
}

function useIsDark() {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    const check = () => setDark(document.documentElement.classList.contains("dark"));
    check();
    const obs = new MutationObserver(check);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);
  return dark;
}

function cleanMetaTags(text: string): string {
  return text
    .replace(/NEXT_WAKE:\s*\d+\s*分钟/g, "")
    .replace(/ACTION:\s*\S+/g, "")
    .replace(/SUMMARY:\s*.+/g, "")
    .replace(/TITLE:\s*.+/g, "")
    .trimEnd();
}

export const MarkdownContent = memo(function MarkdownContent({ content }: { content: string }) {
  const isDark = useIsDark();
  const cleaned = cleanMetaTags(content);

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        pre({ children, ...props }) {
          const codeEl = children as React.ReactElement<{ className?: string; children?: React.ReactNode }>;
          if (codeEl?.props) {
            const className = codeEl.props.className || "";
            const match = /language-(\w+)/.exec(className);
            const text = String(codeEl.props.children).replace(/\n$/, "");
            if (match) {
              return (
                <div className="relative my-2">
                  <CopyButton text={text} />
                  <SyntaxHighlighter
                    style={isDark ? oneDark : oneLight}
                    language={match[1]}
                    PreTag="div"
                    customStyle={{
                      margin: 0,
                      borderRadius: "0.5rem",
                      fontSize: "13px",
                      lineHeight: "1.5",
                      overflowX: "auto",
                      wordBreak: "break-word",
                      whiteSpace: "pre-wrap",
                      paddingRight: "2rem",
                    }}
                  >
                    {text}
                  </SyntaxHighlighter>
                </div>
              );
            }
            return (
              <div className="relative my-2">
                <CopyButton text={text} />
                <pre className="bg-warm-thinking rounded-lg p-3 pr-8 text-sm font-mono overflow-x-auto whitespace-pre-wrap break-words">
                  <code>{codeEl.props.children}</code>
                </pre>
              </div>
            );
          }
          return <pre {...props}>{children}</pre>;
        },
        code({ className, children, ...props }) {
          const match = /language-(\w+)/.exec(className || "");
          if (match) {
            return <code className={className} {...props}>{children}</code>;
          }
          return (
            <code
              className="px-1.5 py-0.5 rounded bg-warm-thinking text-sm font-mono"
              {...props}
            >
              {children}
            </code>
          );
        },
        p({ children }) {
          return <p className="mb-2 last:mb-0">{children}</p>;
        },
        ul({ children }) {
          return <ul className="list-disc pl-5 mb-2">{children}</ul>;
        },
        ol({ children }) {
          return <ol className="list-decimal pl-5 mb-2">{children}</ol>;
        },
        li({ children }) {
          return <li className="mb-0.5">{children}</li>;
        },
        a({ href, children }) {
          return (
            <a href={href} target="_blank" rel="noopener noreferrer" className="text-warm-accent underline">
              {children}
            </a>
          );
        },
        blockquote({ children }) {
          return (
            <blockquote className="border-l-3 border-warm-accent/40 pl-3 my-2 text-warm-text-secondary italic">
              {children}
            </blockquote>
          );
        },
        table({ children }) {
          return (
            <div className="overflow-x-auto my-2">
              <table className="border-collapse text-sm w-full">{children}</table>
            </div>
          );
        },
        th({ children }) {
          return (
            <th className="border border-warm-border px-3 py-1.5 bg-warm-thinking text-left font-medium">
              {children}
            </th>
          );
        },
        td({ children }) {
          return (
            <td className="border border-warm-border px-3 py-1.5">{children}</td>
          );
        },
        hr() {
          return <hr className="border-warm-border my-3" />;
        },
        h1({ children }) {
          return <h1 className="text-lg font-semibold mb-2 mt-3">{children}</h1>;
        },
        h2({ children }) {
          return <h2 className="text-base font-semibold mb-1.5 mt-2.5">{children}</h2>;
        },
        h3({ children }) {
          return <h3 className="text-sm font-semibold mb-1 mt-2">{children}</h3>;
        },
      }}
    >
      {cleaned}
    </ReactMarkdown>
  );
});
