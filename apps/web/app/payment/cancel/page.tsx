"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { XCircle } from "lucide-react";
import OperationsShell from "@/components/layout/OperationsShell";

export default function PaymentCancelPage() {
  const router = useRouter();
  const t = useTranslations("payment");

  return (
    <OperationsShell active="outbound" title={t("cancelTitle")} description={t("cancelMessage")}>
      <div className="page-card mx-auto max-w-md space-y-6 px-6 py-8 text-center">
        <div className="flex justify-center">
          <div className="flex size-16 items-center justify-center rounded-[16px] bg-red-50">
            <XCircle className="size-9 text-red-500" />
          </div>
        </div>

        <div className="space-y-2">
          <h2 className="text-xl font-bold text-[#211D24]">
            {t("cancelTitle")}
          </h2>
          <p className="text-sm text-[#706A73]">
            {t("cancelMessage")}
          </p>
        </div>

        <div className="pt-4 space-y-3">
          <button
            onClick={() => router.push("/")}
            className="w-full rounded-[10px] bg-[#211D24] py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[#6B2EAA]"
          >
            {t("viewPlans")}
          </button>
          <button
            onClick={() => router.push("/")}
            className="w-full rounded-[10px] bg-[#F5F4F6] py-2.5 text-sm font-semibold text-[#706A73] transition-colors hover:bg-[#EEE7F4] hover:text-[#6B2EAA]"
          >
            {t("backToHome")}
          </button>
        </div>
      </div>
    </OperationsShell>
  );
}
