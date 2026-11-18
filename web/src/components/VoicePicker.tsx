import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Plus, Search } from "lucide-react";
import { type Voice, langName } from "../lib/api";
import { PreviewButton } from "./AudioPlayer";
import { VoiceAvatar, cx } from "./ui";

export function VoicePicker({
  voices, value, onChange, onAddVoice,
}: { voices: Voice[]; value: string; onChange: (id: string) => void; onAddVoice: () => void }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const box = useRef<HTMLDivElement>(null);
  const selected = voices.find((v) => v.id === value);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const filtered = voices.filter(
    (v) => !q || v.name.toLowerCase().includes(q.toLowerCase()) || v.description.toLowerCase().includes(q.toLowerCase()),
  );

  return (
    <div className="relative" ref={box}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 rounded-xl border border-line bg-surface px-3 py-2 text-left hover:bg-surface-2 focus:outline-none focus:ring-4 focus:ring-[var(--ring)]"
      >
        <VoiceAvatar id={selected?.id ?? "x"} size={28} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">{selected?.name ?? "Escolha uma voz"}</span>
          {selected?.description && <span className="block truncate text-xs text-muted">{selected.description}</span>}
        </span>
        <ChevronDown className="size-4 text-muted" />
      </button>
      {open && (
        <div className="absolute z-30 mt-2 w-full min-w-72 rounded-2xl border border-line bg-surface p-2 shadow-xl">
          <div className="relative mb-2">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Buscar voz"
              className="h-9 w-full rounded-lg bg-surface-2 pl-9 pr-3 text-sm outline-none placeholder:text-faint"
            />
          </div>
          <div className="max-h-72 overflow-y-auto">
            {filtered.map((v) => (
              <div
                key={v.id}
                role="option"
                aria-selected={v.id === value}
                onClick={() => { onChange(v.id); setOpen(false); }}
                className={cx(
                  "flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2 hover:bg-surface-2",
                  v.id === value && "bg-surface-2",
                )}
              >
                <VoiceAvatar id={v.id} size={28} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{v.name}</div>
                  <div className="truncate text-xs text-muted">
                    {v.kind === "builtin" ? "Padrão do modelo" : v.is_owner ? "Clonada por você" : "Compartilhada"}
                    {v.language && ` · ${langName(v.language)}`}
                  </div>
                </div>
                {v.has_sample && <PreviewButton src={`/api/voices/${v.id}/sample`} />}
                {v.id === value && <Check className="size-4" />}
              </div>
            ))}
            {filtered.length === 0 && <p className="px-2 py-4 text-center text-sm text-muted">Nenhuma voz encontrada</p>}
          </div>
          <button
            type="button"
            onClick={() => { setOpen(false); onAddVoice(); }}
            className="mt-1 flex w-full items-center gap-2 rounded-lg px-2 py-2 text-sm font-medium hover:bg-surface-2"
          >
            <span className="flex size-7 items-center justify-center rounded-full border border-dashed border-line">
              <Plus className="size-4" />
            </span>
            Clonar nova voz
          </button>
        </div>
      )}
    </div>
  );
}
