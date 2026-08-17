import { describe, expect, it } from 'vitest';
import { stabilizeStreamingMarkdown } from './streamMarkdown';

describe('stabilizeStreamingMarkdown', () => {
  it('closes an unclosed code fence', () => {
    const out = stabilizeStreamingMarkdown('text\n```py\nprint(1)\n');
    expect((out.match(/```/g) ?? []).length % 2).toBe(0);
  });
  it('leaves balanced fences alone', () => {
    const src = 'a\n```js\nx\n```\nb';
    expect(stabilizeStreamingMarkdown(src)).toBe(src);
  });
  it('closes dangling bold at end of text', () => {
    expect(stabilizeStreamingMarkdown('hello **wor')).toBe('hello **wor**');
  });
  it('closes dangling inline code', () => {
    expect(stabilizeStreamingMarkdown('run `npm i')).toBe('run `npm i`');
  });
  it('does not touch inline backticks inside a closed pair', () => {
    expect(stabilizeStreamingMarkdown('a `b` c')).toBe('a `b` c');
  });
  it('does not flip parity on a lone backtick inside a closed fence', () => {
    const src = '```\nUse a single ` character in docs\n```\nSome trailing text';
    expect(stabilizeStreamingMarkdown(src)).toBe(src);
  });
  it('does not flip bold parity on **kwargs inside a closed fence', () => {
    const src = '```py\ndef f(**kwargs):\n    pass\n```\nSome trailing text';
    expect(stabilizeStreamingMarkdown(src)).toBe(src);
  });
  it('does not flip parity on a mid-line ``` inside closed-fence content, with balanced trailing prose', () => {
    const src = '```\nUse ``` to open\n```\ntrailing text without any backticks';
    expect(stabilizeStreamingMarkdown(src)).toBe(src);
  });
  it('still closes a dangling backtick after a mid-line ``` inside closed-fence content', () => {
    const src = '```\nUse ``` to open\n```\ntrailing `dangling';
    expect(stabilizeStreamingMarkdown(src)).toBe('```\nUse ``` to open\n```\ntrailing `dangling`');
  });
});
