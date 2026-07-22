import { cn } from '@/lib/utils';

interface VoiceSignalProps {
  active?: boolean;
  tone?: 'purple' | 'green' | 'neutral';
  compact?: boolean;
}

export default function VoiceSignal({ active = false, tone = 'purple', compact = false }: VoiceSignalProps) {
  return (
    <div
      className={cn(
        'voice-signal-bars',
        `voice-signal-bars--${tone}`,
        active && 'is-active',
        compact && 'is-compact',
      )}
      aria-hidden="true"
    >
      {[9, 17, 25, 14, 29, 20, 11, 23, 15].map((height, index) => (
        <i key={`${height}-${index}`} style={{ height }} />
      ))}
    </div>
  );
}
