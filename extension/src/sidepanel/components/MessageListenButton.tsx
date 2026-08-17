/**
 * MessageListenButton — play assistant reply via browser speechSynthesis.
 */
import { Volume2, VolumeX } from 'lucide-react';
import { useSpeechSynthesis } from '../hooks/useSpeechSynthesis';
import {
  isSpeechSynthesisSupported,
  primeSpeechSynthesisFromUserGesture,
} from '../utils/speech/speechSynthesisCompat';

interface MessageListenButtonProps {
  messageId: string;
  text: string;
  className?: string;
}

export function MessageListenButton({ messageId, text, className = '' }: MessageListenButtonProps) {
  const { isSupported, isSpeaking, toggle } = useSpeechSynthesis(messageId, text);
  const canListen = isSpeechSynthesisSupported() && text.trim().length > 0;

  if (!canListen) return null;

  const label = isSpeaking ? 'Stop' : 'Listen';

  return (
    <button
      type="button"
      onClick={() => {
        primeSpeechSynthesisFromUserGesture();
        toggle(text);
      }}
      disabled={!isSupported && !isSpeaking}
      title={label}
      aria-label={label}
      aria-pressed={isSpeaking}
      className={`inline-flex items-center gap-1 text-2xs text-fg-subtle transition-colors duration-fast ease-tool hover:text-signal ${className}`}
    >
      {isSpeaking ? <VolumeX size={12} strokeWidth={2} /> : <Volume2 size={12} strokeWidth={2} />}
      <span>{label}</span>
    </button>
  );
}
