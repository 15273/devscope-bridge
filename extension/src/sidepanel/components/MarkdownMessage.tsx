/**
 * MarkdownMessage — renders assistant markdown with react-markdown + remark-gfm.
 * Code blocks delegate to CodeBlock for syntax highlighting + copy button.
 *
 * RTL: every block element gets dir="auto" so mixed Hebrew/English content lays
 * out correctly per-paragraph (the browser's bidi algorithm decides direction
 * from each block's first strong character).
 *
 * File paths in inline code are clickable to copy the path.
 */
import { useCallback, useState } from 'react';
import { ExternalLink } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { CodeBlock } from './CodeBlock';
import { openPath } from '../bridge';
import { MixedBidiText } from '../utils/mixedBidiText';
import { stabilizeStreamingMarkdown, useThrottledText } from '../utils/streamMarkdown';
import type { Components } from 'react-markdown';

interface MarkdownMessageProps {
  text: string;
  /** While true, render plain text (no markdown parse) to avoid jank on every chunk. */
  isStreaming?: boolean;
  /** Hebrew/English lessons — per-line bidi without parent RTL fighting English wraps. */
  mixedBidi?: boolean;
}

const MIXED_BIDI_BLOCK = 'bidi-plaintext text-start';

const FILE_PATH_RE = /(^|\/)[\w.-]+\.(csv|json|txt|md|py|ts|tsx|js|jsx|sql|sh|ya?ml|html?|css|pdf|xlsx?|png|jpe?g|svg|log|env|toml|ini|lock)$/i;

function isFilePath(s: string): boolean {
  return s.includes('/') || FILE_PATH_RE.test(s);
}

function InlineCode({ children }: { children: React.ReactNode }) {
  const text = String(children);
  const [copied, setCopied] = useState(false);

  const copy = useCallback(() => {
    navigator.clipboard
      .writeText(text)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => {});
  }, [text]);

  if (isFilePath(text)) {
    const absolute = text.startsWith('/') || text.startsWith('~');
    return (
      <span
        dir="ltr"
        className="inline-flex items-center gap-1 rounded-sm bg-surface px-1 py-0.5 font-mono text-[0.85em]"
      >
        <button
          type="button"
          onClick={copy}
          title={copied ? 'Copied!' : `Click to copy: ${text}`}
          className="text-signal underline decoration-dotted underline-offset-2 hover:text-signal-hover"
        >
          {copied ? 'copied ✓' : children}
        </button>
        {absolute && (
          <button
            type="button"
            onClick={() => openPath(text)}
            title="Open on your machine"
            className="text-fg-subtle transition-colors duration-fast ease-tool hover:text-signal"
          >
            <ExternalLink size={11} strokeWidth={2} />
          </button>
        )}
      </span>
    );
  }

  return (
    <code dir="ltr" className="rounded-sm bg-surface px-1 py-0.5 font-mono text-[0.85em] text-fg">
      {children}
    </code>
  );
}

const components: Components = {
  code({ node: _node, className, children }) {
    const match = /language-(\w+)/.exec(className ?? '');
    const isBlock = match !== null || String(children).includes('\n');
    if (isBlock) {
      return <CodeBlock code={String(children).replace(/\n$/, '')} language={match?.[1] ?? 'text'} />;
    }
    return <InlineCode>{children}</InlineCode>;
  },

  pre({ children }) {
    return <>{children}</>;
  },

  p({ children }) {
    return <p dir="auto" className="mb-2 leading-[1.55] last:mb-0">{children}</p>;
  },

  h1({ children }) {
    return <h1 dir="auto" className="mb-1 mt-3 text-base font-semibold first:mt-0">{children}</h1>;
  },

  h2({ children }) {
    return <h2 dir="auto" className="mb-1 mt-3 text-sm font-semibold first:mt-0">{children}</h2>;
  },

  h3({ children }) {
    return <h3 dir="auto" className="mb-1 mt-2 text-sm font-medium first:mt-0">{children}</h3>;
  },

  ul({ children }) {
    return <ul dir="auto" className="mb-2 list-inside list-disc space-y-0.5 text-sm">{children}</ul>;
  },

  ol({ children }) {
    return <ol dir="auto" className="mb-2 list-inside list-decimal space-y-0.5 text-sm">{children}</ol>;
  },

  li({ children }) {
    return <li dir="auto" className="leading-[1.55]">{children}</li>;
  },

  blockquote({ children }) {
    return (
      <blockquote dir="auto" className="my-2 border-s-2 border-signal/40 ps-3 italic text-fg-muted">
        {children}
      </blockquote>
    );
  },

  a({ href, children }) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-signal underline underline-offset-2 hover:text-signal-hover"
      >
        {children}
      </a>
    );
  },

  hr() {
    return <hr className="my-3 border-line" />;
  },

  table({ children }) {
    return (
      <div className="my-2 overflow-x-auto rounded-md border border-line">
        <table className="w-full border-collapse text-xs">{children}</table>
      </div>
    );
  },

  th({ children }) {
    return (
      <th dir="auto" className="border-b border-line bg-surface px-2 py-1 text-start font-medium text-fg">
        {children}
      </th>
    );
  },

  td({ children }) {
    return <td dir="auto" className="border-b border-line px-2 py-1 text-start text-fg-muted">{children}</td>;
  },
};

function mixedBidiComponents(): Components {
  const block = MIXED_BIDI_BLOCK;
  return {
    ...components,
    p({ children }) {
      return (
        <p dir="auto" className={`mb-2 leading-[1.55] last:mb-0 ${block}`}>
          {children}
        </p>
      );
    },
    h1({ children }) {
      return (
        <h1 dir="auto" className={`mb-1 mt-3 text-base font-semibold first:mt-0 ${block}`}>
          {children}
        </h1>
      );
    },
    h2({ children }) {
      return (
        <h2 dir="auto" className={`mb-1 mt-3 text-sm font-semibold first:mt-0 ${block}`}>
          {children}
        </h2>
      );
    },
    h3({ children }) {
      return (
        <h3 dir="auto" className={`mb-1 mt-2 text-sm font-medium first:mt-0 ${block}`}>
          {children}
        </h3>
      );
    },
    ul({ children }) {
      return <ul dir="auto" className={`mb-2 list-inside list-disc space-y-0.5 text-sm ${block}`}>{children}</ul>;
    },
    ol({ children }) {
      return <ol dir="auto" className={`mb-2 list-inside list-decimal space-y-0.5 text-sm ${block}`}>{children}</ol>;
    },
    li({ children }) {
      return <li dir="auto" className={`leading-[1.55] ${block}`}>{children}</li>;
    },
    blockquote({ children }) {
      return (
        <blockquote dir="auto" className={`my-2 border-s-2 border-signal/40 ps-3 italic text-fg-muted ${block}`}>
          {children}
        </blockquote>
      );
    },
  };
}

export function MarkdownMessage({ text, isStreaming = false, mixedBidi = false }: MarkdownMessageProps) {
  // Hooks must run unconditionally — only the streaming branch below uses the result.
  const throttledText = useThrottledText(text);

  if (isStreaming) {
    if (mixedBidi) {
      return (
        <MixedBidiText
          text={text}
          as="div"
          className="markdown-body whitespace-pre-wrap break-words text-sm leading-[1.55] text-fg"
        />
      );
    }
    return (
      <div dir="auto" className="markdown-body text-sm text-fg">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {stabilizeStreamingMarkdown(throttledText)}
        </ReactMarkdown>
      </div>
    );
  }

  return (
    <div dir="auto" className={`markdown-body text-sm text-fg ${mixedBidi ? MIXED_BIDI_BLOCK : ''}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={mixedBidi ? mixedBidiComponents() : components}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
