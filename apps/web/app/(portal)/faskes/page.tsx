"use client";

import { PortalClaimList } from "@/components/PortalClaims";

export default function FacilityPortalPage() {
  return (
    <PortalClaimList
      base="/faskes"
      title="Portal Faskes: klaim rumah sakit Anda"
      intro="Pantau status klaim pasien Anda dan jawab permintaan dokumen susulan dari asuransi."
      showMember
    />
  );
}
