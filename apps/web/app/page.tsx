"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getToken } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    router.replace(getToken() ? "/klaim" : "/login");
  }, [router]);
  return <div className="p-8 text-sm text-slate-500">Memuat…</div>;
}
