"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getStoredUser, getToken } from "@/lib/api";
import { homeFor } from "@/lib/format";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    router.replace(getToken() ? homeFor(getStoredUser()?.role) : "/login");
  }, [router]);
  return <div className="p-8 text-sm text-slate-500">Memuat…</div>;
}
