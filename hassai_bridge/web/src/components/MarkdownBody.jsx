import { useEffect, useMemo, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { resolveMediaUrl } from "../lib/api.js";
import { ChatImage } from "./ChatImage.jsx";

const REMARK_PLUGINS = [remarkGfm];

function CodeBlock({ language, children, copyLabel, copiedLabel }) {
  const [copied, setCopied] = useState(false);
  const text = String(children).replace(/\n$/, "");

  useEffect(() => {
    if (!copied) return undefined;
    const id = setTimeout(() => setCopied(false), 1600);
    return () => clearTimeout(id);
  }, [copied]);

  return (
    <div className="group/code my-3 overflow-hidden rounded-xl bg-black/40">
      <div className="flex items-center justify-between gap-2 px-3 py-1.5 text-[11px] text-muted-foreground">
        <span className="truncate font-medium uppercase tracking-wide">{language || ""}</span>
        <button
          className="shrink-0 rounded-md px-1.5 py-0.5 hover:bg-white/10 hover:text-foreground"
          type="button"
          onClick={() => {
            navigator.clipboard?.writeText(text).then(() => setCopied(true)).catch(() => {});
          }}
        >
          {copied ? copiedLabel : copyLabel}
        </button>
      </div>
      <pre className="overflow-x-auto px-4 pb-3 text-[13px] leading-6">
        <code>{text}</code>
      </pre>
    </div>
  );
}

function makeComponents(copyLabel, copiedLabel, imageLabels = {}) {
  return {
    pre: ({ children }) => children,
    code({ className, children, ...props }) {
      const language = /language-([a-z0-9+-]+)/i.exec(className || "")?.[1];
      const value = String(children);
      if (className || value.includes("\n")) {
        return (
          <CodeBlock copyLabel={copyLabel} copiedLabel={copiedLabel} language={language}>
            {value}
          </CodeBlock>
        );
      }
      return (
        <code className="rounded-md bg-white/10 px-1.5 py-0.5 text-[13px]" {...props}>
          {children}
        </code>
      );
    },
    a({ href, children }) {
      return (
        <a href={href} rel="noopener noreferrer" target="_blank">
          {children}
        </a>
      );
    },
    table({ children }) {
      return (
        <div className="my-3 overflow-x-auto">
          <table>{children}</table>
        </div>
      );
    },
    img({ src, alt }) {
      return (
        <ChatImage
          alt={alt || ""}
          className="my-2 max-h-80 max-w-full rounded-xl border border-white/10 object-cover"
          closeLabel={imageLabels.closeLabel}
          downloadLabel={imageLabels.downloadLabel}
          openLabel={imageLabels.openLabel}
          src={resolveMediaUrl(src)}
        />
      );
    },
    input({ type, checked, ...props }) {
      if (type === "checkbox") {
        return <input checked={Boolean(checked)} className="mr-2 align-middle" disabled readOnly type="checkbox" />;
      }
      return <input type={type} {...props} />;
    },
  };
}

export function MarkdownBody({
  text,
  copyLabel,
  copiedLabel,
  cursor,
  className = "",
  downloadLabel,
  closeLabel,
  openImageLabel,
}) {
  const components = useMemo(
    () =>
      makeComponents(copyLabel, copiedLabel, {
        downloadLabel,
        closeLabel,
        openLabel: openImageLabel,
      }),
    [copyLabel, copiedLabel, downloadLabel, closeLabel, openImageLabel],
  );

  return (
    <div className={`md-body min-w-0 break-words text-[15px] leading-7 text-foreground ${className}`.trim()}>
      <Markdown components={components} remarkPlugins={REMARK_PLUGINS}>
        {text}
      </Markdown>
      {cursor}
    </div>
  );
}
