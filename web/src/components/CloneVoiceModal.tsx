import { useEffect, useRef, useState } from "react";
import { FileAudio, Mic, Square, Trash2, Upload } from "lucide-react";
import { api, type Voice, LANGUAGE_NAMES } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { AudioPlayer } from "./AudioPlayer";
import { Button, Field, IconButton, Modal, cx, inputCls } from "./ui";

const SAMPLE_SCRIPT =
  "Olá! Estou gravando esta amostra para criar a minha voz digital. Vou falar com calma, em um ambiente " +
  "silencioso, mantendo o mesmo tom do começo ao fim. Assim o resultado fica natural e parecido comigo.";

export function CloneVoiceModal({
  open, onClose, onCreated,
}: { open: boolean; onClose: () => void; onCreated: (v: Voice) => void }) {
  const { user } = useAuth();
  const toast = useToast();
  const [tab, setTab] = useState<"upload" | "record">("upload");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [language, setLanguage] = useState("pt");
  const [shared, setShared] = useState(false);
  const [consent, setConsent] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  // gravação
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const recRef = useRef<MediaRecorder | null>(null);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    if (!open) {
      setFile(null); setName(""); setDescription(""); setConsent(false); setShared(false);
      setTab("upload"); stopRecording();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!file) { setPreview(null); return; }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const pick = (f: File | undefined | null) => {
    if (!f) return;
    if (!f.type.startsWith("audio/") && !f.type.startsWith("video/") && !/\.(wav|mp3|m4a|ogg|webm|flac|aac)$/i.test(f.name)) {
      toast("error", "Envie um arquivo de áudio");
      return;
    }
    setFile(f);
    if (!name) setName(f.name.replace(/\.[^.]+$/, "").slice(0, 60));
  };

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      const rec = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const type = rec.mimeType || "audio/webm";
        const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
        setFile(new File([new Blob(chunks, { type })], `gravacao.${ext}`, { type }));
      };
      rec.start();
      recRef.current = rec;
      setRecording(true);
      setElapsed(0);
      const t0 = Date.now();
      timerRef.current = window.setInterval(() => {
        const s = (Date.now() - t0) / 1000;
        setElapsed(s);
        if (s >= 30) stopRecording();
      }, 200);
    } catch {
      toast("error", "Não foi possível acessar o microfone");
    }
  };

  function stopRecording() {
    if (timerRef.current) window.clearInterval(timerRef.current);
    timerRef.current = null;
    if (recRef.current && recRef.current.state !== "inactive") recRef.current.stop();
    recRef.current = null;
    setRecording(false);
  }

  const submit = async () => {
    if (!file) return toast("error", "Adicione um áudio de referência");
    if (!name.trim()) return toast("error", "Dê um nome para a voz");
    if (!consent) return toast("error", "Confirme que você tem autorização para usar esta voz");
    const fd = new FormData();
    fd.append("file", file);
    fd.append("name", name.trim());
    fd.append("description", description.trim());
    fd.append("language", language);
    fd.append("consent", "true");
    fd.append("shared", String(shared));
    setSaving(true);
    try {
      const { voice } = await api.post<{ voice: Voice }>("/api/voices", fd);
      toast("ok", `Voz “${voice.name}” criada`);
      onCreated(voice);
      onClose();
    } catch (e) {
      toast("error", (e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Clonar voz" wide>
      <p className="mb-4 text-sm text-muted">
        Envie de 10 a 30 segundos de fala limpa, de uma única pessoa, sem música nem ruído de fundo.
      </p>

      <div className="mb-4 inline-flex rounded-full bg-surface-2 p-1 text-sm">
        {(["upload", "record"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cx("rounded-full px-4 py-1.5 font-medium", tab === t ? "bg-surface shadow-sm" : "text-muted")}
          >
            {t === "upload" ? "Enviar arquivo" : "Gravar agora"}
          </button>
        ))}
      </div>

      {file ? (
        <div className="mb-5 rounded-xl border border-line p-3">
          <div className="mb-2 flex items-center gap-2 text-sm">
            <FileAudio className="size-4 text-muted" />
            <span className="flex-1 truncate">{file.name}</span>
            <span className="text-xs text-muted">{(file.size / 1024 / 1024).toFixed(1)} MB</span>
            <IconButton onClick={() => setFile(null)} aria-label="Remover"><Trash2 className="size-4" /></IconButton>
          </div>
          {preview && <AudioPlayer src={preview} />}
        </div>
      ) : tab === "upload" ? (
        <label
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => { e.preventDefault(); setDragOver(false); pick(e.dataTransfer.files[0]); }}
          className={cx(
            "mb-5 flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-4 py-10 text-center transition-colors",
            dragOver ? "border-fg bg-surface-2" : "border-line hover:bg-surface-2",
          )}
        >
          <div className="flex size-10 items-center justify-center rounded-full bg-surface-2"><Upload className="size-5" /></div>
          <span className="text-sm font-medium">Clique ou arraste um arquivo de áudio</span>
          <span className="text-xs text-muted">WAV, MP3, M4A, OGG ou WEBM · até 25 MB</span>
          <input type="file" accept="audio/*,video/webm,video/mp4" className="hidden" onChange={(e) => pick(e.target.files?.[0])} />
        </label>
      ) : (
        <div className="mb-5 rounded-xl border border-line p-4">
          <p className="mb-3 text-xs font-medium uppercase tracking-wide text-muted">Leia em voz alta</p>
          <p className="mb-4 text-[15px] leading-relaxed">{SAMPLE_SCRIPT}</p>
          <div className="flex items-center gap-3">
            {recording ? (
              <Button variant="primary" onClick={stopRecording}><Square className="size-3.5" fill="currentColor" /> Parar</Button>
            ) : (
              <Button variant="primary" onClick={startRecording}><Mic className="size-4" /> Começar a gravar</Button>
            )}
            <span className={cx("text-sm tabular-nums", recording ? "text-danger" : "text-muted")}>
              {recording && "● "}{elapsed.toFixed(0)}s / 30s
            </span>
          </div>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Nome">
          <input className={inputCls} value={name} maxLength={80} onChange={(e) => setName(e.target.value)} placeholder="Ex.: Narrador institucional" />
        </Field>
        <Field label="Idioma principal">
          <select className={inputCls} value={language} onChange={(e) => setLanguage(e.target.value)}>
            {Object.entries(LANGUAGE_NAMES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <div className="sm:col-span-2">
          <Field label="Descrição (opcional)">
            <input className={inputCls} value={description} maxLength={300} onChange={(e) => setDescription(e.target.value)} placeholder="Ex.: Voz masculina, calma, tom grave" />
          </Field>
        </div>
      </div>

      {user?.is_admin && (
        <label className="mt-4 flex items-center gap-2 text-sm">
          <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} className="size-4 accent-[var(--fg)]" />
          Compartilhar com todos os usuários
        </label>
      )}

      <label className="mt-4 flex items-start gap-2.5 rounded-xl bg-surface-2 p-3 text-[13px] leading-snug">
        <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5 size-4 shrink-0 accent-[var(--fg)]" />
        <span>
          Confirmo que esta é a minha voz ou que tenho autorização expressa da pessoa para cloná-la, e que não vou
          usá-la para enganar, se passar por outra pessoa ou violar direitos de terceiros.
        </span>
      </label>

      <div className="mt-5 flex justify-end gap-2">
        <Button onClick={onClose}>Cancelar</Button>
        <Button variant="primary" onClick={submit} loading={saving} disabled={!file || !consent || !name.trim() || recording}>
          Criar voz
        </Button>
      </div>
    </Modal>
  );
}
