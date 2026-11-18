import { useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { Plus, Trash2 } from "lucide-react";
import { api, type User, formatDate } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { PageHeader } from "../components/Layout";
import { Badge, Button, Field, IconButton, Modal, Spinner, inputCls } from "../components/ui";

type Row = User & { created_at: number };

export default function Users() {
  const { user: me } = useAuth();
  const toast = useToast();
  const [users, setUsers] = useState<Row[] | null>(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ email: "", name: "", password: "", is_admin: false });
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    const { users } = await api.get<{ users: Row[] }>("/api/admin/users");
    setUsers(users);
  }, []);
  useEffect(() => { if (me?.is_admin) load(); }, [load, me]);
  if (!me?.is_admin) return <Navigate to="/tts" replace />;

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.post("/api/admin/users", form);
      toast("ok", "Usuário criado");
      setOpen(false);
      setForm({ email: "", name: "", password: "", is_admin: false });
      load();
    } catch (err) {
      toast("error", (err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const remove = async (u: Row) => {
    if (!confirm(`Remover ${u.email}? As vozes e os áudios dessa pessoa também serão apagados.`)) return;
    try {
      await api.del(`/api/admin/users/${u.id}`);
      load();
    } catch (err) {
      toast("error", (err as Error).message);
    }
  };

  return (
    <div className="mx-auto max-w-4xl p-4 sm:p-6 lg:p-8">
      <PageHeader
        title="Usuários"
        subtitle="Quem pode acessar o estúdio. O cadastro público fica desligado por padrão (ALLOW_SIGNUP)."
        actions={<Button variant="primary" onClick={() => setOpen(true)}><Plus className="size-4" /> Novo usuário</Button>}
      />
      {users === null ? (
        <div className="flex justify-center py-16"><Spinner /></div>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-line bg-surface">
          {users.map((u, i) => (
            <div key={u.id} className={"flex items-center gap-3 px-4 py-3.5 " + (i ? "border-t border-line" : "")}>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate font-medium">{u.name || u.email}</span>
                  {u.is_admin && <Badge tone="ok">Admin</Badge>}
                </div>
                <div className="truncate text-xs text-muted">{u.email} · desde {formatDate(u.created_at)}</div>
              </div>
              {u.id !== me.id && (
                <IconButton onClick={() => remove(u)} aria-label="Remover"><Trash2 className="size-4" /></IconButton>
              )}
            </div>
          ))}
        </div>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title="Novo usuário">
        <form onSubmit={create} className="flex flex-col gap-4">
          <Field label="Nome"><input className={inputCls} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="E-mail"><input className={inputCls} type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <Field label="Senha inicial" hint="Mínimo de 8 caracteres. Envie à pessoa por um canal seguro.">
            <input className={inputCls} type="text" required minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="size-4 accent-[var(--fg)]" checked={form.is_admin} onChange={(e) => setForm({ ...form, is_admin: e.target.checked })} />
            Administrador
          </label>
          <div className="flex justify-end gap-2">
            <Button type="button" onClick={() => setOpen(false)}>Cancelar</Button>
            <Button variant="primary" type="submit" loading={saving}>Criar</Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
