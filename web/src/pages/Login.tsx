import { useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Logo } from "../components/Layout";
import { Button, Card, Field, inputCls } from "../components/ui";

function safeNext(next: string | null): string {
  // só caminhos internos (evita open redirect)
  if (next && next.startsWith("/") && !next.startsWith("//")) return next;
  return "/tts";
}

export default function Login() {
  const { user, refresh, signupAllowed, appName } = useAuth();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const fromOAuth = next.startsWith("/oauth/");

  if (user && !fromOAuth) return <Navigate to={next} replace />;
  if (user && fromOAuth) {
    window.location.href = next;
    return null;
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (mode === "login") await api.post("/api/auth/login", { email, password });
      else await api.post("/api/auth/signup", { email, password, name });
      if (fromOAuth) {
        window.location.href = next; // fluxo OAuth é renderizado pelo servidor
        return;
      }
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-full items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex justify-center"><Logo name={appName} /></div>
        <Card className="p-6">
          <h1 className="text-xl font-semibold">{mode === "login" ? "Entrar" : "Criar conta"}</h1>
          <p className="mb-5 mt-1 text-sm text-muted">
            {fromOAuth ? "Entre para autorizar o acesso do aplicativo." : "Gere fala e clone vozes no seu estúdio."}
          </p>
          <form onSubmit={submit} className="flex flex-col gap-4">
            {mode === "signup" && (
              <Field label="Nome">
                <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
              </Field>
            )}
            <Field label="E-mail">
              <input className={inputCls} type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
            </Field>
            <Field label="Senha" hint={mode === "signup" ? "Mínimo de 8 caracteres" : undefined}>
              <input
                className={inputCls} type="password" required minLength={mode === "signup" ? 8 : undefined}
                value={password} onChange={(e) => setPassword(e.target.value)}
                autoComplete={mode === "login" ? "current-password" : "new-password"}
              />
            </Field>
            {error && <p className="text-sm text-danger">{error}</p>}
            <Button variant="primary" size="lg" type="submit" loading={busy}>
              {mode === "login" ? "Entrar" : "Criar conta"}
            </Button>
          </form>
          {signupAllowed && (
            <p className="mt-5 text-center text-sm text-muted">
              {mode === "login" ? "Ainda não tem conta? " : "Já tem conta? "}
              <button className="font-medium text-fg underline-offset-4 hover:underline" onClick={() => { setMode(mode === "login" ? "signup" : "login"); setError(""); }}>
                {mode === "login" ? "Criar conta" : "Entrar"}
              </button>
            </p>
          )}
        </Card>
      </div>
    </div>
  );
}
