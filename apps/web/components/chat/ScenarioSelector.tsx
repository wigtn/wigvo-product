'use client';

import { useCallback, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import {
  ArrowLeftRight,
  Bot,
  Building2,
  Check,
  Keyboard,
  Languages,
  Mic2,
  PhoneOutgoing,
  Scissors,
  Search,
  Send,
  Stethoscope,
  UtensilsCrossed,
  Wrench,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import LanguageDropdown from '@/components/common/LanguageDropdown';
import type { ScenarioSubType, ScenarioType } from '@/shared/types';
import type { CommunicationMode } from '@/shared/call-types';
import { SUPPORTED_LANGUAGES, getDefaultLanguagePairForLocale } from '@/shared/call-types';
import { cn } from '@/lib/utils';

interface QuickAction {
  icon: LucideIcon;
  scenarioType: ScenarioType;
  subType: ScenarioSubType;
  labelKey: string;
  descKey: string;
}

const QUICK_ACTIONS: QuickAction[] = [
  { icon: UtensilsCrossed, scenarioType: 'RESERVATION', subType: 'RESTAURANT', labelKey: 'restaurant', descKey: 'restaurantDesc' },
  { icon: Scissors, scenarioType: 'RESERVATION', subType: 'SALON', labelKey: 'salon', descKey: 'salonDesc' },
  { icon: Stethoscope, scenarioType: 'RESERVATION', subType: 'HOSPITAL', labelKey: 'hospital', descKey: 'hospitalDesc' },
  { icon: Building2, scenarioType: 'RESERVATION', subType: 'HOTEL', labelKey: 'hotel', descKey: 'hotelDesc' },
  { icon: Search, scenarioType: 'INQUIRY', subType: 'OTHER', labelKey: 'inquiry', descKey: 'inquiryDesc' },
  { icon: Wrench, scenarioType: 'AS_REQUEST', subType: 'OTHER', labelKey: 'asRequest', descKey: 'asRequestDesc' },
];

const MODE_OPTIONS: Array<{
  mode: CommunicationMode;
  icon: LucideIcon;
  titleKey: 'voiceToVoice' | 'textToVoice' | 'fullAgent';
  subtitleKey: 'voiceToVoiceSubtitle' | 'textToVoiceSubtitle' | 'fullAgentSubtitle';
  descriptionKey: 'voiceToVoiceDesc' | 'textToVoiceDesc' | 'fullAgentDesc';
}> = [
  { mode: 'voice_to_voice', icon: Mic2, titleKey: 'voiceToVoice', subtitleKey: 'voiceToVoiceSubtitle', descriptionKey: 'voiceToVoiceDesc' },
  { mode: 'text_to_voice', icon: Keyboard, titleKey: 'textToVoice', subtitleKey: 'textToVoiceSubtitle', descriptionKey: 'textToVoiceDesc' },
  { mode: 'full_agent', icon: Bot, titleKey: 'fullAgent', subtitleKey: 'fullAgentSubtitle', descriptionKey: 'fullAgentDesc' },
];

interface ScenarioSelectorProps {
  onSelect: (
    scenarioType: ScenarioType,
    subType: ScenarioSubType,
    communicationMode: CommunicationMode,
    sourceLang: string,
    targetLang: string,
  ) => void;
  disabled?: boolean;
}

export function ScenarioSelector({ onSelect, disabled = false }: ScenarioSelectorProps) {
  const t = useTranslations('scenario');
  const tLang = useTranslations('scenario.lang');
  const tModes = useTranslations('scenario.modes');
  const tQuick = useTranslations('scenario.quick');
  const locale = useLocale();
  const defaultPair = getDefaultLanguagePairForLocale(locale);
  const [sourceLang, setSourceLang] = useState(defaultPair.source.code);
  const [targetLang, setTargetLang] = useState(defaultPair.target.code);
  const [selectedMode, setSelectedMode] = useState<CommunicationMode | null>(null);
  const [freeText, setFreeText] = useState('');

  const sourceLangObj = SUPPORTED_LANGUAGES.find((language) => language.code === sourceLang);
  const targetLangObj = SUPPORTED_LANGUAGES.find((language) => language.code === targetLang);

  const handleSwapLanguages = useCallback(() => {
    setSourceLang(targetLang);
    setTargetLang(sourceLang);
  }, [sourceLang, targetLang]);

  const handleDirectContinue = useCallback(() => {
    if (disabled || !selectedMode || selectedMode === 'full_agent') return;
    onSelect('INQUIRY', 'OTHER', selectedMode, sourceLang, targetLang);
  }, [disabled, onSelect, selectedMode, sourceLang, targetLang]);

  const handleQuickAction = useCallback((action: QuickAction) => {
    if (disabled) return;
    onSelect(action.scenarioType, action.subType, 'full_agent', sourceLang, targetLang);
  }, [disabled, onSelect, sourceLang, targetLang]);

  const handleFreeTextSubmit = useCallback(() => {
    if (!freeText.trim() || disabled) return;
    onSelect('INQUIRY', 'OTHER', 'full_agent', sourceLang, targetLang);
  }, [disabled, freeText, onSelect, sourceLang, targetLang]);

  return (
    <div className="styled-scrollbar h-full overflow-y-auto bg-transparent">
      <div>
        <div className="ops-panel-header">
          <div className="flex items-center gap-2.5">
            <span className="grid size-8 place-items-center rounded-lg bg-[#F1EFF2] text-[#4D4852]"><PhoneOutgoing className="size-4" /></span>
            <h2 className="text-sm font-bold text-[#1E1E28]">{t('setupTitle')}</h2>
          </div>
          <span className="text-[11px] font-medium tabular-nums text-[#918B98]">01 · 02</span>
        </div>

        <div className="ops-panel-body grid">
          <section className="ops-subsection" aria-labelledby="language-section-title">
            <div className="mb-4 flex items-center gap-2.5">
              <span className="text-[10px] font-bold tabular-nums text-[#918B98]">01</span>
              <h3 id="language-section-title" className="text-sm font-bold text-[#1E1E28]">{t('languageSection')}</h3>
            </div>
            <div className="grid grid-cols-[minmax(0,1fr)_40px_minmax(0,1fr)] items-end gap-2.5 sm:grid-cols-[minmax(0,1fr)_44px_minmax(0,1fr)] sm:gap-4">
              <div>
                <p className="mb-2 text-[11px] font-semibold text-[#686375]">{tLang('myLang')}</p>
                <LanguageDropdown value={sourceLang} onChange={setSourceLang} disabled={disabled} />
              </div>
              <button
                type="button"
                onClick={handleSwapLanguages}
                disabled={disabled}
                className="mb-0.5 grid size-10 place-items-center rounded-[9px] border border-[#CEC9D4] bg-white text-[#686375] transition-colors hover:border-[#1E1E28] hover:bg-[#F5F3F6] hover:text-[#1E1E28] focus-visible:!outline-[#1E1E28] disabled:opacity-50"
                aria-label={t('swapLanguages')}
              >
                <ArrowLeftRight className="size-4" />
              </button>
              <div>
                <p className="mb-2 text-[11px] font-semibold text-[#686375]">{tLang('theirLang')}</p>
                <LanguageDropdown value={targetLang} onChange={setTargetLang} disabled={disabled} />
              </div>
            </div>

            <div className="mt-4 grid gap-2 border-t border-[#EEEAEF] pt-4 text-[11px] text-[#686375] sm:grid-cols-2">
              <p className="flex items-center gap-2">
                <Languages className="size-3.5 shrink-0 text-[#686375]" />
                <span>{tLang('flowSend', { source: sourceLangObj?.label ?? '', target: targetLangObj?.label ?? '' })}</span>
              </p>
              <p className="flex items-center gap-2 sm:justify-end">
                <Languages className="size-3.5 shrink-0 text-[#686375]" />
                <span>{tLang('flowReceive', { source: sourceLangObj?.label ?? '' })}</span>
              </p>
            </div>
          </section>

          <section className="ops-subsection" aria-labelledby="mode-section-title">
            <div className="mb-4 flex items-end justify-between gap-4">
              <div className="flex items-center gap-2.5">
                <span className="text-[10px] font-bold tabular-nums text-[#918B98]">02</span>
                <h3 id="mode-section-title" className="text-sm font-bold text-[#1E1E28]">{t('modeSection')}</h3>
              </div>
              <span className="text-[11px] text-[#918B98]">{t('modeHint')}</span>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              {MODE_OPTIONS.map((option) => {
                const Icon = option.icon;
                const selected = selectedMode === option.mode;
                return (
                  <button
                    key={option.mode}
                    type="button"
                    disabled={disabled}
                    aria-pressed={selected}
                    onClick={() => setSelectedMode(option.mode)}
                    className={cn(
                      'group relative min-h-[152px] rounded-[10px] border p-4 text-left transition-[border-color,background-color,transform] duration-150 focus-visible:!outline-[#1E1E28] active:scale-[0.99] disabled:opacity-50 sm:min-h-[160px]',
                      selected
                        ? 'border-[#1E1E28] bg-white'
                        : 'border-[#E3E0E8] bg-white hover:border-[#BEB8C4]',
                    )}
                  >
                    <span className={cn(
                      'grid size-10 place-items-center rounded-[9px] border transition-colors',
                      selected
                        ? 'border-[#1E1E28] bg-[#1E1E28] text-white'
                        : 'border-[#E3E0E8] bg-white text-[#5F5A68]',
                    )}>
                      <Icon className="size-[18px]" />
                    </span>
                    <span className="mt-4 block text-[10px] font-bold uppercase tracking-[0.1em] text-[#918B98]">{tModes(option.subtitleKey)}</span>
                    <strong className="mt-1 block text-sm text-[#1E1E28]">{tModes(option.titleKey)}</strong>
                    <span className="mt-1.5 block text-xs leading-5 text-[#686375]">{tModes(option.descriptionKey)}</span>
                    <span className={cn(
                      'absolute right-4 top-4 grid size-5 place-items-center rounded-full border',
                      selected ? 'border-[#1E1E28] bg-[#1E1E28] text-white' : 'border-[#BEB8C4] bg-white text-transparent',
                    )}>
                      <Check className="size-3" />
                    </span>
                  </button>
                );
              })}
            </div>

            {selectedMode && selectedMode !== 'full_agent' && (
              <div className="mt-4 flex flex-col gap-3 border-t border-[#EEEAEF] pt-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className="text-[11px] font-semibold text-[#918B98]">{t('selectedMode')}</p>
                  <p className="mt-1 truncate text-sm font-bold text-[#1E1E28]">
                    {tModes(selectedMode === 'voice_to_voice' ? 'voiceToVoice' : 'textToVoice')}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={handleDirectContinue}
                  disabled={disabled}
                  className="inline-flex h-11 shrink-0 items-center justify-center rounded-[9px] bg-[#1E1E28] px-5 text-sm font-bold text-white transition-colors hover:bg-[#34313B] focus-visible:!outline-[#1E1E28] disabled:opacity-50"
                >
                  {t('continueWithMode')}
                </button>
              </div>
            )}

            {selectedMode === 'full_agent' && (
              <section className="mt-4 border-t border-[#EEEAEF] pt-4" aria-labelledby="agent-purpose-title">
                <div className="mb-4">
                  <h3 id="agent-purpose-title" className="text-sm font-bold text-[#1E1E28]">{t('agentPurposeTitle')}</h3>
                  <p className="mt-1 text-xs text-[#686375]">{t('agentPurposeDescription')}</p>
                </div>
                <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
                  {QUICK_ACTIONS.map((action) => {
                    const Icon = action.icon;
                    return (
                      <button
                        key={`${action.scenarioType}-${action.subType}`}
                        type="button"
                        disabled={disabled}
                        onClick={() => handleQuickAction(action)}
                        className="group flex min-h-[92px] items-center gap-3 rounded-[9px] border border-transparent bg-[#F6F4F7] p-3 text-left transition-colors hover:border-[#CEC9D4] hover:bg-white focus-visible:!outline-[#1E1E28] disabled:opacity-50"
                      >
                        <span className="grid size-9 shrink-0 place-items-center rounded-[8px] border border-[#E3E0E8] bg-white text-[#5F5A68]"><Icon className="size-4" /></span>
                        <span className="min-w-0">
                          <strong className="block text-xs text-[#1E1E28]">{tQuick(action.labelKey)}</strong>
                          <span className="mt-0.5 block text-[10px] text-[#918B98]">{tQuick(action.descKey)}</span>
                        </span>
                      </button>
                    );
                  })}
                </div>
                <div className="mt-4 flex items-center gap-2 border-t border-[#EEEAEF] pt-4">
                  <input
                    type="text"
                    value={freeText}
                    onChange={(event) => setFreeText(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
                        event.preventDefault();
                        handleFreeTextSubmit();
                      }
                    }}
                    disabled={disabled}
                    placeholder={t('freeInputPlaceholder')}
                    className="h-11 min-w-0 flex-1 rounded-[9px] border border-[#CEC9D4] bg-white px-3.5 text-sm text-[#1E1E28] placeholder:text-[#918B98] focus:border-[#1E1E28] focus:outline-none focus:ring-3 focus:ring-[#EEEAEF] disabled:opacity-50"
                  />
                  <button
                    type="button"
                    onClick={handleFreeTextSubmit}
                    disabled={!freeText.trim() || disabled}
                    className="grid size-11 shrink-0 place-items-center rounded-[9px] bg-[#1E1E28] text-white transition-colors hover:bg-[#34313B] focus-visible:!outline-[#1E1E28] disabled:bg-[#CEC9D4]"
                    aria-label={t('submitRequest')}
                  >
                    <Send className="size-4" />
                  </button>
                </div>
              </section>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

export default ScenarioSelector;
