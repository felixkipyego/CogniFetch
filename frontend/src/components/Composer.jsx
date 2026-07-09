import { useState, useRef, useEffect } from 'react';

export default function Composer({ onSend, isStreaming, disabled }) {
  const [value, setValue] = useState('');
  const textareaRef = useRef(null);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  }, [value]);

  function submit() {
    const text = value.trim();
    if (!text || isStreaming || disabled) return;
    setValue('');
    onSend(text);
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <div className="composer">
      <form
        className="composer__form"
        onSubmit={e => { e.preventDefault(); submit(); }}
      >
        <textarea
          ref={textareaRef}
          className="composer__textarea"
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={isStreaming ? 'Waiting for response…' : 'Ask about your documents…'}
          disabled={isStreaming || disabled}
          rows={1}
          aria-label="Message input"
        />
        <button
          type="submit"
          className="btn btn--primary composer__send"
          disabled={!value.trim() || isStreaming || disabled}
          aria-label="Send message"
        >
          Send
        </button>
      </form>
      <p className="composer__hint">Enter to send · Shift+Enter for newline</p>
    </div>
  );
}
