"use client";

import { PortalClaimList } from "@/components/PortalClaims";

export default function MemberPortalPage() {
  return (
    <PortalClaimList
      base="/peserta"
      title="Klaim saya"
      intro="Status klaim rawat inap Anda dan penjelasan keputusan asuransi."
      showMember={false}
    />
  );
}
