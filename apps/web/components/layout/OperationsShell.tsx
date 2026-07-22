'use client';

import { useEffect, useState, type ReactNode } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';
import { History, LayoutDashboard, LogOut, Menu, PhoneIncoming, PhoneOutgoing, X } from 'lucide-react';
import { createClient } from '@/lib/supabase/client';
import LanguageSwitcher from '@/components/common/LanguageSwitcher';
import { cn } from '@/lib/utils';
import wigtnLogo from '../../../../docs/design/assets/wigtn-logo-white.png';

type OperationsSection = 'dashboard' | 'outbound' | 'inbound' | 'history';

interface OperationsShellProps {
  active: OperationsSection;
  title: string;
  description?: string;
  children: ReactNode;
  headerActions?: ReactNode;
  workspace?: boolean;
}

const sections: Array<{
  key: OperationsSection;
  href: string;
  icon: typeof PhoneOutgoing;
  labelKey: 'dashboard' | 'outbound' | 'inbound' | 'history';
}> = [
  { key: 'dashboard', href: '/', icon: LayoutDashboard, labelKey: 'dashboard' },
  { key: 'inbound', href: '/inbound', icon: PhoneIncoming, labelKey: 'inbound' },
  { key: 'outbound', href: '/outbound', icon: PhoneOutgoing, labelKey: 'outbound' },
  { key: 'history', href: '/history', icon: History, labelKey: 'history' },
];

export default function OperationsShell({
  active,
  title,
  description,
  children,
  headerActions,
  workspace = false,
}: OperationsShellProps) {
  const router = useRouter();
  const t = useTranslations('sidebar');
  const tCommon = useTranslations('common');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [userEmail, setUserEmail] = useState('');

  useEffect(() => {
    let activeRequest = true;
    const supabase = createClient();
    void supabase.auth.getUser().then(({ data }) => {
      if (activeRequest) setUserEmail(data.user?.email ?? '');
    });
    return () => { activeRequest = false; };
  }, []);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDrawerOpen(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [drawerOpen]);

  const handleSignOut = async () => {
    const supabase = createClient();
    await supabase.auth.signOut();
    localStorage.removeItem('currentConversationId');
    localStorage.removeItem('currentCommunicationMode');
    localStorage.removeItem('currentSourceLang');
    localStorage.removeItem('currentTargetLang');
    router.push('/login');
  };

  const sidebar = (
    <div className="flex h-full flex-col bg-[#15151E] px-3.5 pb-4 pt-5 text-white">
      <Link href="/" className="px-2 pb-5" onClick={() => setDrawerOpen(false)}>
        <Image src={wigtnLogo} alt="WIGTN" className="h-auto w-[106px]" priority />
        <span className="mt-1.5 block text-[11px] font-semibold tracking-[0.08em] text-[#AAA3AE]">
          WIGVO OPERATIONS
        </span>
      </Link>

      <div className="mb-5 rounded-[10px] border border-[#302D37] bg-[#1E1E28] px-3 py-2.5">
        <span className="block text-[10px] font-semibold tracking-[0.08em] text-[#8D8691]">WORKSPACE</span>
        <span className="mt-1 block text-xs font-semibold text-[#E5DFE8]">{t('operations')}</span>
      </div>

      <span className="px-3 pb-2 text-[10px] font-bold tracking-[0.1em] text-[#8D8691]">{t('menu')}</span>
      <nav className="grid gap-1" aria-label={t('menu')}>
        {sections.map((section) => {
          const Icon = section.icon;
          const selected = active === section.key;
          return (
            <Link
              key={section.key}
              href={section.href}
              onClick={() => setDrawerOpen(false)}
              aria-current={selected ? 'page' : undefined}
              className={cn(
                'relative grid h-11 w-full grid-cols-[24px_minmax(0,1fr)] items-center gap-3 rounded-[9px] px-3 text-[13px] transition-colors',
                selected
                  ? 'bg-[#292632] font-semibold text-white before:absolute before:-left-3.5 before:h-[22px] before:w-[3px] before:rounded-r-full before:bg-[#9B51E0]'
                  : 'text-[#AAA4B1] hover:bg-[#211F29] hover:text-[#F0EDF3]',
              )}
            >
              <span className="grid size-6 place-items-center"><Icon className="size-[18px]" strokeWidth={1.8} /></span>
              <span>{t(section.labelKey)}</span>
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto">
        <div className="mb-3 border-t border-[#2B272E] pt-3">
          <LanguageSwitcher tone="dark" />
        </div>
        <div className="grid grid-cols-[36px_minmax(0,1fr)_auto] items-center gap-2.5 border-t border-[#2B272E] pt-3">
          <div className="grid size-9 place-items-center rounded-[10px] bg-[#38313D] text-xs font-bold text-[#E3D9EC]">
            {(userEmail[0] || 'W').toUpperCase()}
          </div>
          <div className="min-w-0">
            <strong className="block truncate text-xs font-semibold text-[#EEE9F1]">{t('operator')}</strong>
            <span className="mt-0.5 block truncate text-[10px] text-[#9A939E]">{userEmail || 'WIGVO'}</span>
          </div>
          <button
            type="button"
            onClick={handleSignOut}
            aria-label={tCommon('logout')}
            className="grid size-9 place-items-center rounded-lg text-[#9A939E] transition-colors hover:bg-[#2B272E] hover:text-white"
          >
            <LogOut className="size-4" />
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="ops-shell">
      <aside className="hidden h-dvh w-56 shrink-0 lg:block">{sidebar}</aside>

      <div
        className={cn(
          'fixed inset-0 z-40 bg-black/35 transition-opacity lg:hidden',
          drawerOpen ? 'opacity-100' : 'pointer-events-none opacity-0',
        )}
        onClick={() => setDrawerOpen(false)}
        aria-hidden="true"
      />
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-50 w-[min(82vw,280px)] transition-transform duration-200 lg:hidden',
          drawerOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <button
          type="button"
          onClick={() => setDrawerOpen(false)}
          className="absolute right-3 top-4 z-10 grid size-9 place-items-center rounded-lg text-[#A49DA8] hover:bg-[#2B272E] hover:text-white"
          aria-label="메뉴 닫기"
        >
          <X className="size-5" />
        </button>
        {sidebar}
      </aside>

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="ops-topbar">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              onClick={() => setDrawerOpen(true)}
              className="grid size-10 shrink-0 place-items-center rounded-[9px] border border-[#E4E1E6] bg-white text-[#706A73] lg:hidden"
              aria-label="메뉴 열기"
            >
              <Menu className="size-[18px]" />
            </button>
            <div className="min-w-0">
              <h1 className="truncate text-[17px] font-bold tracking-[-0.025em] text-[#1E1E28] md:text-[19px]">{title}</h1>
              {description && <p className="mt-0.5 hidden truncate text-xs text-[#686375] sm:block">{description}</p>}
            </div>
          </div>
          {headerActions && <div className="flex shrink-0 items-center gap-2">{headerActions}</div>}
        </header>

        <main className={cn('ops-main', workspace && 'ops-main--workspace')}>
          <div className={cn('ops-content', workspace && 'ops-content--workspace')}>{children}</div>
          {!workspace && (
            <footer className="ops-footer">
              <div className="flex items-center gap-3">
                <span className="flex w-[104px] items-center" aria-label="WIGTN">
                  <Image src="/wigtn-logo-navy.png" alt="WIGTN" width={1600} height={800} className="h-auto w-full" />
                </span>
                <span className="border-l border-[#D5D1D8] pl-3">WIGVO Operations</span>
              </div>
              <span>© {new Date().getFullYear()} WIGTN</span>
            </footer>
          )}
        </main>
      </div>
    </div>
  );
}
