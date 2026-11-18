import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Mic2, Pencil, Plus, Search, Share2, Trash2 } from "lucide-react";
import { api, type Voice, formatDate, langName, LANGUAGE_NAMES } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { PreviewButton } from "../components/AudioPlayer";
import { CloneVoiceModal } from "../components/CloneVoiceModal";
import { PageHeader } from "../components/Layout";
import { Badge, Button, Empty, Field, IconButton, Modal, Spinner, VoiceAvatar, inputCls } from "../components/ui";

export default function Voices() {
  const { user } = useAuth();
  const toast = useToast();
  const nav = useNavigate();
  const [voices, setVoices] = useState<Voice[] | null>(null);
  const [q, setQ] = useState("");
  const [cloneOpen, setCloneOpen] = useState(false);
  const [editing, setEditing] = useState<Voice | null>(null);
  const [filter, setFilter] = useState<"all" | "mine" | "shared">("all");

  const load = useCallback(async () => {
    const { voices } = await api.get<{ voices: Voice[] }>("/api/voices");
    setVoices(voices);
  }, []);
  useEffect(() => { load(); }, [load]);

  const remove = async (v: Voice) => {
    if (!confirm(`Excluir a voz “${v.name}”? Essa ação não pode ser desfeita.`)) return;
    try {
      await api.del(`/api/voices/${v.id}`);
      toast("ok", "Voz excluída");
      load();
    } catch (e) {
      toast("error", (e as Error).message);
    }
  };

  const toggleShare = async (v: Voice) => {
    try {
      await api.patch(`/api/voices/${v.id}`, { is_shared: !v.is_shared });
      toast("ok", v.is_shared ? "Voz agora é privada" : "Voz compartilhada com todos");
      load();
    } catch (e) {
      toast("error", (e as Error).message);
    }
  };

  const list = (voices ?? []).filter((v) => {
    if (filter === "mine" && !v.is_owner) return false;
    if (filter === "shared" && !(v.kind === "builtin" || (v.is_shared && !v.is_owner))) return false;
    const s = q.toLowerCase();
    return !s || v.name.toLowerCase().includes(s) || v.description.toLowerCase().includes(s);
  });

  return (
    <div className="mx-auto max-w-5xl p-4 sm:p-6 lg:p-8">
      <PageHeader
        title="Vozes"
        subtitle="Sua biblioteca de vozes. Clone uma voz a partir de alguns segundos de áudio."
        actions={<Button variant="primary" onClick={() => setCloneOpen(true)}><Plus className="size-4" /> Clonar voz</Button>}
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative min-w-56 flex-1">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
          <input className={inputCls + " pl-9"} placeholder="Buscar vozes" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="inline-flex rounded-full bg-surface-2 p-1 text-sm">
          {([["all", "Todas"], ["mine", "Minhas"], ["shared", "Padrão e compartilhadas"]] as const).map(([k, label]) => (
            <button
              key={k}
              onClick={() => setFilter(k)}
              className={"rounded-full px-3 py-1.5 font-medium " + (filter === k ? "bg-surface shadow-sm" : "text-muted")}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {voices === null ? (
        <div className="flex justify-center py-16"><Spinner /></div>
      ) : list.length === 0 ? (
        <Empty icon={<Mic2 className="size-5" />} title="Nenhuma voz por aqui">
          Clique em <b>Clonar voz</b> para criar a primeira.
        </Empty>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-line bg-surface">
          {list.map((v, i) => (
            <div key={v.id} className={"flex items-center gap-3 px-4 py-3.5 " + (i ? "border-t border-line" : "")}>
              <VoiceAvatar id={v.id} size={40} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate font-medium">{v.name}</span>
                  {v.kind === "builtin" && <Badge>Padrão</Badge>}
                  {v.kind === "cloned" && <Badge>Clonada</Badge>}
                  {v.is_shared && v.kind === "cloned" && <Badge tone="ok">Compartilhada</Badge>}
                  {v.language && <Badge>{langName(v.language)}</Badge>}
                </div>
                <div className="truncate text-sm text-muted">
                  {v.description || (v.kind === "builtin" ? "Voz que acompanha o modelo" : `Criada em ${formatDate(v.created_at)}`)}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {v.has_sample && <PreviewButton src={`/api/voices/${v.id}/sample`} />}
                {(v.is_owner || user?.is_admin) && v.kind === "cloned" && (
                  <>
                    <IconButton onClick={() => setEditing(v)} aria-label="Editar" title="Editar"><Pencil className="size-4" /></IconButton>
                    {user?.is_admin && (
                      <IconButton onClick={() => toggleShare(v)} aria-label="Compartilhar" title={v.is_shared ? "Tornar privada" : "Compartilhar com todos"}>
                        <Share2 className={"size-4 " + (v.is_shared ? "text-ok" : "")} />
                      </IconButton>
                    )}
                    <IconButton onClick={() => remove(v)} aria-label="Excluir" title="Excluir"><Trash2 className="size-4" /></IconButton>
                  </>
                )}
                <Button size="sm" className="ml-1" onClick={() => nav(`/tts?voice=${v.id}`)}>Usar</Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <CloneVoiceModal open={cloneOpen} onClose={() => setCloneOpen(false)} onCreated={() => load()} />
      <EditVoiceModal voice={editing} onClose={() => setEditing(null)} onSaved={load} />
    </div>
  );
}

function EditVoiceModal({ voice, onClose, onSaved }: { voice: Voice | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [language, setLanguage] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (voice) { setName(voice.name); setDescription(voice.description); setLanguage(voice.language); }
  }, [voice]);
  const save = async () => {
    if (!voice) return;
    setSaving(true);
    try {
      await api.patch(`/api/voices/${voice.id}`, { name, description, language });
      toast("ok", "Voz atualizada");
      onSaved();
      onClose();
    } catch (e) {
      toast("error", (e as Error).message);
    } finally {
      setSaving(false);
    }
  };
  return (
    <Modal open={!!voice} onClose={onClose} title="Editar voz">
      <div className="flex flex-col gap-4">
        <Field label="Nome"><input className={inputCls} value={name} maxLength={80} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Descrição"><input className={inputCls} value={description} maxLength={300} onChange={(e) => setDescription(e.target.value)} /></Field>
        <Field label="Idioma principal">
          <select className={inputCls} value={language} onChange={(e) => setLanguage(e.target.value)}>
            <option value="">—</option>
            {Object.entries(LANGUAGE_NAMES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancelar</Button>
          <Button variant="primary" onClick={save} loading={saving}>Salvar</Button>
        </div>
      </div>
    </Modal>
  );
}
