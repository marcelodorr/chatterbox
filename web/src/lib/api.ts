export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "X-Requested-With": "fetch" };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(url, { method, headers, body: payload, credentials: "same-origin" });
  if (!res.ok) {
    let message = `Erro ${res.status}`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") message = data.detail;
      else if (Array.isArray(data.detail)) message = data.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* resposta sem JSON */
    }
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(url: string) => request<T>("GET", url),
  post: <T>(url: string, body?: unknown) => request<T>("POST", url, body ?? {}),
  patch: <T>(url: string, body?: unknown) => request<T>("PATCH", url, body ?? {}),
  del: <T>(url: string) => request<T>("DELETE", url),
};

// ------------------------------------------------------------------ tipos
export type User = { id: string; email: string; name: string; is_admin: boolean };

export type Voice = {
  id: string;
  name: string;
  description: string;
  language: string;
  kind: "builtin" | "cloned";
  is_shared: boolean;
  is_owner: boolean;
  has_sample: boolean;
  sample_duration: number | null;
  created_at: number;
};

export type Model = {
  id: string;
  label: string;
  description: string;
  kind: "mtl" | "turbo";
  languages: string[];
  loaded: boolean;
  default: boolean;
};

export type AppConfig = {
  app_name: string;
  public_url: string;
  mcp_url: string;
  max_text_chars: number;
  inference: { online: boolean; device: string | null; default: string | null; models: Model[]; error?: string };
};

export type Generation = {
  id: string;
  status: "queued" | "running" | "done" | "error";
  error: string | null;
  text: string;
  voice_id: string | null;
  voice_name: string;
  model: string;
  language: string;
  params: Record<string, number>;
  duration: number | null;
  source: "web" | "mcp";
  created_at: number;
  finished_at: number | null;
  queue_position?: number;
  audio_url?: string;
};

export type Connection = {
  client_id: string;
  client_name: string | null;
  client_uri: string | null;
  logo_uri: string | null;
  scope: string;
  created_at: number;
  last_used_at: number | null;
};

export const LANGUAGE_NAMES: Record<string, string> = {
  ar: "Árabe", da: "Dinamarquês", de: "Alemão", el: "Grego", en: "Inglês", es: "Espanhol",
  fi: "Finlandês", fr: "Francês", he: "Hebraico", hi: "Hindi", it: "Italiano", ja: "Japonês",
  ko: "Coreano", ms: "Malaio", nl: "Holandês", no: "Norueguês", pl: "Polonês", pt: "Português",
  ru: "Russo", sv: "Sueco", sw: "Suaíli", tr: "Turco", zh: "Chinês",
};

export function langName(code: string): string {
  return LANGUAGE_NAMES[code] ?? code.toUpperCase();
}

export function formatDuration(sec: number | null | undefined): string {
  if (sec == null || !isFinite(sec)) return "0:00";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function formatDate(ts: number): string {
  return new Date(ts * 1000).toLocaleString("pt-BR", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

/** Acompanha uma geração até terminar (long-polling no backend). */
export async function waitForGeneration(
  id: string,
  onUpdate: (g: Generation) => void,
  signal?: AbortSignal,
): Promise<Generation> {
  for (;;) {
    if (signal?.aborted) throw new DOMException("aborted", "AbortError");
    try {
      const { generation } = await api.get<{ generation: Generation }>(`/api/generations/${id}?wait=20`);
      onUpdate(generation);
      if (generation.status === "done" || generation.status === "error") return generation;
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) throw e;
      await new Promise((r) => setTimeout(r, 3000));
    }
  }
}
