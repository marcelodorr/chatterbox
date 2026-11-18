import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AlertCircle, AudioLines, RotateCcw, Sparkles } from "lucide-react";
import { api, type Generation, type Voice, langName, waitForGeneration } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { AudioPlayer } from "../components/AudioPlayer";
import { CloneVoiceModal } from "../components/CloneVoiceModal";
import { VoicePicker } from "../components/VoicePicker";
import { Badge, Button, Equalizer, Field, Slider, VoiceAvatar, inputCls } from "../components/ui";

const DEFAULTS = { exaggeration: 0.5, cfg_weight: 0.5, temperature: 0.8 };

function load<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v ? (JSON.parse(v) as T) : fallback;
  } catch {
    return fallback;
  }
}
function save(key: string, v: unknown) {
  try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* sem storage */ }
}

export default function TextToSpeech() {
  const { config, reloadConfig } = useAuth();
  const toast = useToast();
  const [params] = useSearchParams();
  const models = config?.inference.models ?? [];
  const maxChars = config?.max_text_chars ?? 5000;

  const [text, setText] = useState(() => load("tts.text", ""));
  const [voices, setVoices] = useState<Voice[]>([]);
  const [voiceId, setVoiceId] = useState<string>(() => params.get("voice") ?? load("tts.voice", "default"));
  const [model, setModel] = useState<string>(() => load("tts.model", ""));
  const [language, setLanguage] = useState<string>(() => load("tts.lang", "pt"));
  const [settings, setSettings] = useState(() => load("tts.settings", DEFAULTS));
  const [items, setItems] = useState<Generation[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [cloneOpen, setCloneOpen] = useState(false);
  const [justFinished, setJustFinished] = useState<string | null>(null);

  const currentModel = useMemo(
    () => models.find((m) => m.id === model) ?? models.find((m) => m.default) ?? models[0],
    [models, model],
  );
  const langs = currentModel?.languages ?? ["pt"];

  useEffect(() => { save("tts.text", text); }, [text]);
  useEffect(() => { save("tts.voice", voiceId); }, [voiceId]);
  useEffect(() => { if (currentModel) save("tts.model", currentModel.id); }, [currentModel]);
  useEffect(() => { save("tts.lang", language); }, [language]);
  useEffect(() => { save("tts.settings", settings); }, [settings]);
  useEffect(() => {
    if (!langs.includes(language)) setLanguage(langs.includes("pt") ? "pt" : langs[0]);
  }, [langs, language]);

  const loadVoices = useCallback(async () => {
    const { voices } = await api.get<{ voices: Voice[] }>("/api/voices");
    setVoices(voices);
    setVoiceId((id) => (voices.some((v) => v.id === id) ? id : "default"));
  }, []);

  const track = useCallback((g: Generation) => {
    const update = (ng: Generation) => setItems((list) => list.map((x) => (x.id === ng.id ? ng : x)));
    waitForGeneration(g.id, update)
      .then((final) => {
        if (final.status === "done") setJustFinished(final.id);
        if (final.status === "error") toast("error", final.error ?? "Falha na geração");
      })
      .catch(() => {});
  }, [toast]);

  useEffect(() => {
    loadVoices();
    reloadConfig();
    api.get<{ generations: Generation[] }>("/api/generations?limit=8").then(({ generations }) => {
      setItems(generations);
      generations.filter((g) => g.status === "queued" || g.status === "running").forEach(track);
    });
  }, [loadVoices, reloadConfig, track]);

  const generate = async () => {
    if (!text.trim()) return;
    setSubmitting(true);
    try {
      const { generation } = await api.post<{ generation: Generation }>("/api/generations", {
        text, voice_id: voiceId, model: currentModel?.id, language,
        ...(currentModel?.kind === "turbo" ? { temperature: settings.temperature } : settings),
      });
      setItems((list) => [generation, ...list]);
      track(generation);
    } catch (e) {
      toast("error", (e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const onKey = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") generate();
  };

  const busy = items.some((g) => g.status === "queued" || g.status === "running");
  const offline = config && !config.inference.online;
  const isTurbo = currentModel?.kind === "turbo";

  return (
    <div className="flex min-h-full flex-col lg:flex-row">
      {/* Coluna principal */}
      <div className="flex min-w-0 flex-1 flex-col p-4 sm:p-6 lg:p-8">
        <h1 className="mb-5 text-[22px] font-semibold tracking-tight">Texto para fala</h1>

        {offline && (
          <div className="mb-4 flex items-start gap-2 rounded-xl border border-line bg-surface p-3 text-sm">
            <AlertCircle className="mt-0.5 size-4 shrink-0 text-danger" />
            <span>O motor de voz está offline. Você pode enfileirar gerações; elas rodam quando ele voltar.</span>
          </div>
        )}

        <div className="flex flex-col rounded-2xl border border-line bg-surface focus-within:ring-4 focus-within:ring-[var(--ring)]">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value.slice(0, maxChars))}
            onKeyDown={onKey}
            placeholder={isTurbo
              ? "Type the text here... Tags like [laugh], [chuckle] and [cough] are supported."
              : "Comece a digitar ou cole aqui o texto que você quer transformar em fala..."}
            className="min-h-[260px] flex-1 resize-y rounded-t-2xl bg-transparent p-5 text-[15.5px] leading-relaxed outline-none placeholder:text-faint"
          />
          <div className="flex flex-wrap items-center gap-3 border-t border-line px-4 py-3">
            <span className="text-xs tabular-nums text-muted">
              {text.length.toLocaleString("pt-BR")} / {maxChars.toLocaleString("pt-BR")}
            </span>
            <span className="hidden text-xs text-faint sm:inline">Ctrl/⌘ + Enter para gerar</span>
            <Button
              variant="primary" className="ml-auto" onClick={generate}
              loading={submitting} disabled={!text.trim()}
            >
              <Sparkles className="size-4" /> Gerar fala
            </Button>
          </div>
        </div>

        <div className="mt-8">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold">Gerações recentes</h2>
            {busy && <span className="flex items-center gap-2 text-xs text-muted"><Equalizer /> processando</span>}
          </div>
          {items.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-line p-8 text-center text-sm text-muted">
              <AudioLines className="mx-auto mb-2 size-5" />
              Seus áudios aparecem aqui.
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {items.map((g) => <GenerationRow key={g.id} g={g} autoPlay={g.id === justFinished} />)}
            </div>
          )}
        </div>
      </div>

      {/* Painel de configurações */}
      <aside className="w-full shrink-0 border-t border-line bg-surface p-4 sm:p-6 lg:w-[340px] lg:border-l lg:border-t-0">
        <div className="flex flex-col gap-5 lg:sticky lg:top-6">
          <Field label="Voz">
            <VoicePicker voices={voices} value={voiceId} onChange={setVoiceId} onAddVoice={() => setCloneOpen(true)} />
          </Field>

          <Field label="Modelo" hint={currentModel?.description}>
            <select className={inputCls} value={currentModel?.id ?? ""} onChange={(e) => setModel(e.target.value)}>
              {models.length === 0 && <option value="">Indisponível</option>}
              {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </Field>

          <Field label="Idioma">
            <select className={inputCls} value={language} onChange={(e) => setLanguage(e.target.value)}>
              {langs.map((l) => <option key={l} value={l}>{langName(l)}</option>)}
            </select>
          </Field>

          <div className="h-px bg-line" />

          {!isTurbo && (
            <>
              <Slider
                label="Expressividade" min={0.25} max={2} step={0.05}
                value={settings.exaggeration} left="Neutra" right="Dramática"
                onChange={(v) => setSettings((s) => ({ ...s, exaggeration: v }))}
              />
              <Slider
                label="Ritmo e fidelidade" min={0} max={1} step={0.05}
                value={settings.cfg_weight} left="Mais lento / livre" right="Mais fiel"
                onChange={(v) => setSettings((s) => ({ ...s, cfg_weight: v }))}
              />
            </>
          )}
          <Slider
            label="Variação" min={0.1} max={1.5} step={0.05}
            value={settings.temperature} left="Estável" right="Criativa"
            onChange={(v) => setSettings((s) => ({ ...s, temperature: v }))}
          />
          <button
            onClick={() => setSettings(DEFAULTS)}
            className="flex items-center gap-1.5 self-start text-xs font-medium text-muted hover:text-fg"
          >
            <RotateCcw className="size-3.5" /> Restaurar padrões
          </button>
          <p className="text-xs leading-relaxed text-faint">
            Dica: para falas mais dramáticas, aumente a expressividade (~0.7) e reduza o ritmo (~0.3).
            Se a voz de referência for de outro idioma, use ritmo 0 para evitar sotaque.
          </p>
        </div>
      </aside>

      <CloneVoiceModal
        open={cloneOpen}
        onClose={() => setCloneOpen(false)}
        onCreated={(v) => { loadVoices().then(() => setVoiceId(v.id)); }}
      />
    </div>
  );
}

export function GenerationRow({ g, autoPlay, actions }: { g: Generation; autoPlay?: boolean; actions?: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-3 sm:p-4">
      <div className="flex items-start gap-3">
        <VoiceAvatar id={g.voice_id ?? "default"} size={30} />
        <div className="min-w-0 flex-1">
          <div className="mb-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
            <span className="font-medium text-fg">{g.voice_name}</span>
            <span>·</span>
            <span>{langName(g.language)}</span>
            <span>·</span>
            <span>{g.model}</span>
            {g.source === "mcp" && <Badge>via MCP</Badge>}
            {g.status === "queued" && <Badge tone="warn">Na fila{g.queue_position ? ` · ${g.queue_position} antes` : ""}</Badge>}
            {g.status === "running" && <Badge tone="warn"><Equalizer /> Gerando</Badge>}
            {g.status === "error" && <Badge tone="error">Erro</Badge>}
          </div>
          <p className="line-clamp-2 text-sm">{g.text}</p>
          {g.status === "error" && <p className="mt-1 text-xs text-danger">{g.error}</p>}
          {g.status === "done" && g.audio_url && (
            <div className="mt-2.5">
              <AudioPlayer src={g.audio_url} downloadName={`${g.voice_name}-${g.id}.wav`} autoPlay={autoPlay} />
            </div>
          )}
        </div>
        {actions}
      </div>
    </div>
  );
}
