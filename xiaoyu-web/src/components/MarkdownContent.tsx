"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneLight, oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { useEffect, useState } from "react";

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

export function MarkdownContent({ content }: { content: string }) {
  const isDark = useIsDark();
  const cleaned = cleanMetaTags(content);

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        code({ className, children, ...props }) {
          const match = /language-(\w+)/.exec(className || "");
          const text = String(children).replace(/\n$/, "");
          if (match) {
            return (
              <SyntaxHighlighter
                style={isDark ? oneDark : oneLight}
                language={match[1]}
                PreTag="div"
                customStyle={{
                  margin: "0.5em 0",
                  borderRadius: "0.5rem",
                  fontSize: "13px",
                  lineHeight: "1.5",
                }}
              >
                {text}
              </SyntaxHighlighter>
            );
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
}
