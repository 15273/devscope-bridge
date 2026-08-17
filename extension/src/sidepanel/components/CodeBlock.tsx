/**
 * CodeBlock — syntax-highlighted code with a copy button.
 * Uses react-syntax-highlighter/prism-light for smallest possible bundle.
 *
 * The code surface is always dark (oneDark) — it is the most visually dominant
 * element in an assistant message, which is correct for a coding tool.
 */
import { useState, useCallback } from 'react';
import { Check, Copy } from 'lucide-react';
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';

// Register only common languages to keep bundle small.
import tsx from 'react-syntax-highlighter/dist/esm/languages/prism/tsx';
import typescript from 'react-syntax-highlighter/dist/esm/languages/prism/typescript';
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript';
import jsx from 'react-syntax-highlighter/dist/esm/languages/prism/jsx';
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python';
import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash';
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json';
import css from 'react-syntax-highlighter/dist/esm/languages/prism/css';
import markdown from 'react-syntax-highlighter/dist/esm/languages/prism/markdown';
import yaml from 'react-syntax-highlighter/dist/esm/languages/prism/yaml';

SyntaxHighlighter.registerLanguage('tsx', tsx);
SyntaxHighlighter.registerLanguage('typescript', typescript);
SyntaxHighlighter.registerLanguage('ts', typescript);
SyntaxHighlighter.registerLanguage('javascript', javascript);
SyntaxHighlighter.registerLanguage('js', javascript);
SyntaxHighlighter.registerLanguage('jsx', jsx);
SyntaxHighlighter.registerLanguage('python', python);
SyntaxHighlighter.registerLanguage('py', python);
SyntaxHighlighter.registerLanguage('bash', bash);
SyntaxHighlighter.registerLanguage('sh', bash);
SyntaxHighlighter.registerLanguage('shell', bash);
SyntaxHighlighter.registerLanguage('json', json);
SyntaxHighlighter.registerLanguage('css', css);
SyntaxHighlighter.registerLanguage('markdown', markdown);
SyntaxHighlighter.registerLanguage('md', markdown);
SyntaxHighlighter.registerLanguage('yaml', yaml);
SyntaxHighlighter.registerLanguage('yml', yaml);

interface CodeBlockProps {
  code: string;
  language?: string;
}

export function CodeBlock({ code, language = 'text' }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }).catch(() => {});
  }, [code]);

  const lineCount = code.split('\n').length;

  return (
    <div className="group relative my-2 overflow-hidden rounded-lg border border-black/30 text-xs">
      {/* Language label + line count + copy button row */}
      <div className="flex items-center justify-between bg-[#1a1a1a] px-3 py-1.5">
        <div className="flex items-center gap-2">
          <span className="font-mono text-2xs uppercase tracking-wide text-zinc-400">
            {language}
          </span>
          <span className="font-mono text-2xs text-zinc-600">
            {lineCount} {lineCount === 1 ? 'line' : 'lines'}
          </span>
        </div>
        <button
          onClick={handleCopy}
          aria-label="Copy code"
          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-2xs text-zinc-400 opacity-30 transition-all duration-fast ease-tool hover:bg-white/10 hover:text-white group-hover:opacity-100"
        >
          {copied ? (
            <>
              <Check size={12} strokeWidth={2.5} />
              Copied
            </>
          ) : (
            <>
              <Copy size={12} strokeWidth={2} />
              Copy
            </>
          )}
        </button>
      </div>
      <SyntaxHighlighter
        language={language}
        style={oneDark}
        customStyle={{
          margin: 0,
          borderRadius: 0,
          fontSize: '0.75rem',
          lineHeight: '1.55',
          padding: '0.75rem',
        }}
        codeTagProps={{ style: { fontFamily: "'JetBrains Mono Variable', ui-monospace, monospace" } }}
        wrapLongLines
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
}
