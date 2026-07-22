'use client';

import { useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';
import { createClient } from '@/lib/supabase/client';
import { Loader2, Mail, Lock } from 'lucide-react';

export default function LoginForm({ showSignup = false }: { showSignup?: boolean }) {
  const router = useRouter();
  const t = useTranslations('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submittingRef = useRef(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submittingRef.current) return;
    submittingRef.current = true;
    setError(null);
    setIsLoading(true);

    try {
      const supabase = createClient();

      const { error: signInError } = await supabase.auth.signInWithPassword({
        email,
        password,
      });

      if (signInError) {
        if (signInError.message.includes('Invalid login credentials')) {
          setError(t('errors.invalidCredentials'));
        } else if (signInError.message.includes('Email not confirmed')) {
          setError(t('errors.emailNotConfirmed'));
        } else {
          setError(signInError.message);
        }
        return;
      }

      router.push('/');
      router.refresh();
    } catch {
      setError(t('errors.generic'));
    } finally {
      setIsLoading(false);
      submittingRef.current = false;
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      {/* 이메일 */}
      <div className="relative">
        <Mail className="absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-[#8A838D]" />
        <input
          type="email"
          placeholder={t('email')}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          className="h-12 w-full rounded-[9px] border border-[#D1CCD4] bg-white pl-11 pr-4 text-sm text-[#211D24] transition-colors placeholder:text-[#9A939E] hover:border-[#BBB5BE] focus:border-[#9B51E0] focus:outline-none focus:ring-2 focus:ring-[#F1E7FA]"
        />
      </div>

      {/* 비밀번호 */}
      <div className="relative">
        <Lock className="absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-[#8A838D]" />
        <input
          type="password"
          placeholder={t('password')}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          className="h-12 w-full rounded-[9px] border border-[#D1CCD4] bg-white pl-11 pr-4 text-sm text-[#211D24] transition-colors placeholder:text-[#9A939E] hover:border-[#BBB5BE] focus:border-[#9B51E0] focus:outline-none focus:ring-2 focus:ring-[#F1E7FA]"
        />
      </div>

      {/* 에러 */}
      {error && (
        <p className="rounded-[9px] border border-[#EECACA] bg-[#FAECEB] px-3 py-2 text-center text-sm text-[#A83C3C]">
          {error}
        </p>
      )}

      {/* 로그인 버튼 */}
      <button
        type="submit"
        disabled={isLoading}
        className="flex h-12 w-full items-center justify-center gap-2 rounded-[9px] bg-[#1E1E28] text-sm font-bold text-white transition-colors hover:bg-[#15151E] disabled:opacity-50"
      >
        {isLoading ? (
          <>
            <Loader2 className="size-4 animate-spin" />
            {t('submitting')}
          </>
        ) : (
          t('submit')
        )}
      </button>

      {/* 회원가입 */}
      {showSignup && (
        <p className="text-center text-sm text-[#8A838D]">
          {t('noAccount')}{' '}
          <a href="/signup" className="font-semibold text-[#6B2EAA] hover:underline">{t('signUp')}</a>
        </p>
      )}
    </form>
  );
}
