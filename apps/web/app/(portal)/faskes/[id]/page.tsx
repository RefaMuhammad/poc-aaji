"use client";

import { useParams } from "next/navigation";
import { PortalClaimView } from "@/components/PortalClaims";

export default function FacilityClaimPage() {
  const { id } = useParams<{ id: string }>();
  return <PortalClaimView id={id} base="/faskes" canUpload />;
}
