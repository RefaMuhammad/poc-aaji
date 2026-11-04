"use client";

import type { User } from "./types";

const TOKEN_KEY = "mab_token";
const USER_KEY = "mab_user";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function getStoredUser(): User | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

export function saveSession(token: string, user: User) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  } catch {
    /* abaikan */
  }
}

function errorText(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg).replace(/^Value error, /, "") : String(d)))
        .join("; ");
    }
  }
  return `Permintaan gagal (HTTP ${status})`;
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`/api${path}`, { ...init, headers, cache: "no-store" });
  if (res.status === 401 && !path.startsWith("/auth/login")) {
    clearSession();
    if (typeof window !== "undefined") window.location.href = "/login";
  }
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* bukan JSON */
    }
    throw new ApiError(res.status, errorText(body, res.status));
  }
  return res;
}

export async function apiJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && typeof init.body === "string") headers.set("Content-Type", "application/json");
  const res = await apiFetch(path, { ...init, headers });
  return (await res.json()) as T;
}

/** Unduh file dari API (butuh token, jadi tidak bisa pakai <a href> biasa). */
export async function downloadFile(path: string, fallbackName: string) {
  const res = await apiFetch(path);
  const blob = await res.blob();
  const cd = res.headers.get("content-disposition") || "";
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
  const name = match ? decodeURIComponent(match[1]) : fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** URL blob untuk gambar yang butuh token (pratinjau halaman dokumen). */
export async function blobUrl(path: string): Promise<string> {
  const res = await apiFetch(path);
  return URL.createObjectURL(await res.blob());
}
