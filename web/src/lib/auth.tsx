import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type AppConfig, type User } from "./api";

type AuthState = {
  user: User | null;
  loading: boolean;
  signupAllowed: boolean;
  appName: string;
  config: AppConfig | null;
  refresh: () => Promise<void>;
  reloadConfig: () => Promise<void>;
  logout: () => Promise<void>;
};

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [signupAllowed, setSignupAllowed] = useState(false);
  const [appName, setAppName] = useState("Estúdio de Voz");
  const [config, setConfig] = useState<AppConfig | null>(null);

  const reloadConfig = useCallback(async () => {
    try {
      setConfig(await api.get<AppConfig>("/api/config"));
    } catch {
      /* ignora */
    }
  }, []);

  const refresh = useCallback(async () => {
    const me = await api.get<{ user: User | null; signup_allowed: boolean; app_name: string }>("/api/auth/me");
    setUser(me.user);
    setSignupAllowed(me.signup_allowed);
    setAppName(me.app_name);
    document.title = me.app_name;
    if (me.user) await reloadConfig();
  }, [reloadConfig]);

  useEffect(() => {
    refresh().finally(() => setLoading(false));
  }, [refresh]);

  const logout = useCallback(async () => {
    await api.post("/api/auth/logout");
    setUser(null);
    setConfig(null);
  }, []);

  return (
    <Ctx.Provider value={{ user, loading, signupAllowed, appName, config, refresh, reloadConfig, logout }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth fora do AuthProvider");
  return ctx;
}
