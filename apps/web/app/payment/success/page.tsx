"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { CheckCircle } from "lucide-react";
import OperationsShell from "@/components/layout/OperationsShell";

function PaymentSuccessContent() {
  const router = useRouter();
  const t = useTranslations("payment");
  const searchParams = useSearchParams();

  useEffect(() => {
    const sessionId = searchParams.get("session_id");
    if (sessionId) {
      // TODO: Verify payment with server
    }
  }, [searchParams]);

  return (
    <OperationsShell active="outbound" title={t("successTitle")} description={t("successMessage")}>
      <div className="page-card mx-auto max-w-md space-y-6 px-6 py-8 text-center">
        <div className="flex justify-center">
          <div className="flex size-16 items-center justify-center rounded-[16px] bg-[#EDF6F2]">
            <CheckCircle className="size-9 text-[#23805C]" />
          </div>
        </div>

        <div className="space-y-2">
          <h2 className="text-xl font-bold text-[#211D24]">
            {t("successTitle")}
          </h2>
          <p className="text-sm text-[#706A73]">
            {t("successMessage")}
          </p>
        </div>

        <div className="pt-4 space-y-3">
          <button
            onClick={() => router.push("/")}
            className="w-full rounded-[10px] bg-[#1E1E28] py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[#15151E]"
          >
            {t("backToHome")}
          </button>
        </div>
      </div>
    </OperationsShell>
  );
}

export default function PaymentSuccessPage() {
  return (
    <Suspense
      fallback={
        <div className="grid h-dvh place-items-center bg-[#F5F4F6] text-sm text-[#706A73]">Loading...</div>
      }
    >
      <PaymentSuccessContent />
    </Suspense>
  );
}
