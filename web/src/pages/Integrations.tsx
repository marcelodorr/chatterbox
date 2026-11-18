import { useCallback, useEffect, useState } from "react";
import { Check, Copy, Link2, Unplug } from "lucide-react";
import { api, type Connection, formatDate } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { PageHeader } from "../components/Layout";
import { Button, Card, Empty } from "../components/ui";

function CopyField({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center gap-2 rounded-xl border border-line bg-surface-2 p-1.5 pl-3">
      <code className="min-w-0 flex-1 truncate text-sm">{value}</code>
      <Button
        size="sm"
        onClick={async () => {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />} {copied ? "Copiado" : "Copiar"}
      </Button>
    </div>
  );
}

function Steps({ items }: { items: React.ReactNode[] }) {
  return (
    <ol className="flex flex-col gap-2.5 text-sm">
      {items.map((s, i) => (
        <li key={i} className="flex gap-3">
          <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-surface-2 text-[11px] font-semibold">{i + 1}</span>
          <span className="text-muted [&_b]:font-medium [&_b]:text-fg">{s}</span>
        </li>
      ))}
    </ol>
  );
}

export default function Integrations() {
  const { config } = useAuth();
  const toast = useToast();
  const [conns, setConns] = useState<Connection[] | null>(null);
  const mcpUrl = config?.mcp_url ?? `${window.location.origin}/mcp`;
  const isLocal = /localhost|127\.0\.0\.1/.test(mcpUrl) || mcpUrl.startsWith("http://");

  const load = useCallback(async () => {
    const { connections } = await api.get<{ connections: Connection[] }>("/api/connections");
    setConns(connections);
  }, []);
  useEffect(() => { load(); }, [load]);

  const revoke = async (c: Connection) => {
    if (!confirm(`Desconectar “${c.client_name || c.client_id}”? O app perderá o acesso imediatamente.`)) return;
    await api.del(`/api/connections/${encodeURIComponent(c.client_id)}`);
    toast("ok", "Acesso revogado");
    load();
  };

  return (
    <div className="mx-auto max-w-4xl p-4 sm:p-6 lg:p-8">
      <PageHeader
        title="Claude e ChatGPT"
        subtitle="Conecte o estúdio como servidor MCP. O login usa OAuth: cada pessoa autoriza com a própria conta."
      />

      <Card className="mb-6 p-5">
        <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><Link2 className="size-4" /> URL do servidor MCP</div>
        <CopyField value={mcpUrl} />
        {isLocal && (
          <p className="mt-2 text-xs text-danger">
            Claude e ChatGPT só conectam em uma URL pública com HTTPS. Configure PUBLIC_URL com o domínio do seu servidor.
          </p>
        )}
      </Card>

      <div className="mb-8 grid gap-4 md:grid-cols-2">
        <Card className="p-5">
          <h2 className="mb-1 font-semibold">Claude</h2>
          <p className="mb-4 text-xs text-muted">claude.ai, Claude Desktop e apps móveis</p>
          <Steps items={[
            <>Abra <b>Configurações → Conectores</b>.</>,
            <>Clique em <b>Adicionar conector personalizado</b>.</>,
            <>Dê um nome (ex.: “{config?.app_name ?? "Estúdio de Voz"}”) e cole a <b>URL do servidor MCP</b>. Deixe os campos de OAuth Client ID/Secret vazios.</>,
            <>Clique em <b>Conectar</b>, faça login aqui e clique em <b>Permitir</b>.</>,
            <>Numa conversa, peça: <i>“Gere um áudio dizendo ‘Bem-vindo!’ com a minha voz”</i>.</>,
          ]} />
          <p className="mt-4 text-xs text-faint">Planos Team/Enterprise: um administrador adiciona o conector para a organização.</p>
        </Card>
        <Card className="p-5">
          <h2 className="mb-1 font-semibold">ChatGPT</h2>
          <p className="mb-4 text-xs text-muted">chatgpt.com (planos com modo desenvolvedor)</p>
          <Steps items={[
            <>Em <b>Configurações → Apps e conectores → Configurações avançadas</b>, ative o <b>Modo desenvolvedor</b>.</>,
            <>Volte em <b>Apps e conectores</b> e clique em <b>Criar</b>.</>,
            <>Cole a <b>URL do servidor MCP</b> e escolha autenticação <b>OAuth</b>.</>,
            <>Conclua o login aqui e clique em <b>Permitir</b>.</>,
            <>Numa conversa, ative o app no menu <b>+</b> e peça o áudio.</>,
          ]} />
          <p className="mt-4 text-xs text-faint">Os nomes dos menus podem mudar conforme a versão do app.</p>
        </Card>
      </div>

      <h2 className="mb-3 text-sm font-semibold">Apps conectados</h2>
      {conns && conns.length === 0 ? (
        <Card><Empty icon={<Unplug className="size-5" />} title="Nenhum app conectado">Quando você autorizar o Claude ou o ChatGPT, eles aparecem aqui.</Empty></Card>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-line bg-surface">
          {(conns ?? []).map((c, i) => (
            <div key={c.client_id} className={"flex items-center gap-3 px-4 py-3.5 " + (i ? "border-t border-line" : "")}>
              {c.logo_uri?.startsWith("https://") ? (
                <img src={c.logo_uri} alt="" referrerPolicy="no-referrer" className="size-9 rounded-lg object-cover" />
              ) : (
                <div className="flex size-9 items-center justify-center rounded-lg bg-surface-2 text-sm font-semibold">
                  {(c.client_name || "?").slice(0, 1).toUpperCase()}
                </div>
              )}
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{c.client_name || "App sem nome"}</div>
                <div className="truncate text-xs text-muted">
                  Autorizado em {formatDate(c.created_at)}
                  {c.last_used_at ? ` · último uso ${formatDate(c.last_used_at)}` : ""}
                </div>
              </div>
              <Button size="sm" variant="danger" onClick={() => revoke(c)}>Desconectar</Button>
            </div>
          ))}
        </div>
      )}

      <Card className="mt-8 p-5">
        <h2 className="mb-2 text-sm font-semibold">Ferramentas disponíveis no MCP</h2>
        <ul className="grid gap-x-6 gap-y-1.5 text-sm text-muted sm:grid-cols-2">
          <li><code className="text-fg">list_voices</code> · lista as vozes</li>
          <li><code className="text-fg">list_models</code> · modelos e idiomas</li>
          <li><code className="text-fg">generate_speech</code> · gera o áudio</li>
          <li><code className="text-fg">get_generation</code> · status e link</li>
          <li><code className="text-fg">list_generations</code> · histórico</li>
          <li><code className="text-fg">clone_voice</code> · clona por URL de áudio</li>
        </ul>
      </Card>
    </div>
  );
}
