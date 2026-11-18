import { useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { AudioLines, History, LogOut, Menu, Mic2, Plug, Users, X } from "lucide-react";
import { useAuth } from "../lib/auth";
import { IconButton, cx } from "./ui";

export function Logo({ name }: { name: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <div className="flex size-7 items-center justify-center rounded-lg bg-accent text-accent-fg">
        <svg viewBox="0 0 24 24" className="size-4" fill="currentColor" aria-hidden>
          <rect x="5" y="7" width="2.6" height="10" rx="1.3" />
          <rect x="10.7" y="4" width="2.6" height="16" rx="1.3" />
          <rect x="16.4" y="8.5" width="2.6" height="7" rx="1.3" />
        </svg>
      </div>
      <span className="text-[15px] font-semibold tracking-tight">{name}</span>
    </div>
  );
}

function NavItem({ to, icon, children, onClick }: { to: string; icon: ReactNode; children: ReactNode; onClick?: () => void }) {
  return (
    <NavLink
      to={to}
      onClick={onClick}
      className={({ isActive }) =>
        cx(
          "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
          isActive ? "bg-surface-2 font-medium text-fg" : "text-muted hover:bg-surface-2 hover:text-fg",
        )
      }
    >
      {icon}
      {children}
    </NavLink>
  );
}

export function Layout() {
  const { user, appName, logout, config } = useAuth();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  const close = () => setOpen(false);
  const online = config?.inference.online;

  const nav = (
    <>
      <div className="px-3 pb-6 pt-1"><Logo name={appName} /></div>
      <p className="px-3 pb-1.5 text-[11px] font-medium uppercase tracking-wider text-faint">Criar</p>
      <nav className="flex flex-col gap-0.5">
        <NavItem to="/tts" icon={<AudioLines className="size-4" />} onClick={close}>Texto para fala</NavItem>
        <NavItem to="/voices" icon={<Mic2 className="size-4" />} onClick={close}>Vozes</NavItem>
        <NavItem to="/history" icon={<History className="size-4" />} onClick={close}>Histórico</NavItem>
      </nav>
      <p className="px-3 pb-1.5 pt-6 text-[11px] font-medium uppercase tracking-wider text-faint">Conectar</p>
      <nav className="flex flex-col gap-0.5">
        <NavItem to="/integrations" icon={<Plug className="size-4" />} onClick={close}>Claude e ChatGPT</NavItem>
        {user?.is_admin && <NavItem to="/users" icon={<Users className="size-4" />} onClick={close}>Usuários</NavItem>}
      </nav>
      <div className="mt-auto pt-6">
        <div className="mb-3 flex items-center gap-2 px-3 text-xs text-muted">
          <span className={cx("size-2 rounded-full", online ? "bg-ok" : "bg-danger")} />
          {online ? `Motor de voz online (${config?.inference.device?.toUpperCase()})` : "Motor de voz offline"}
        </div>
        <div className="flex items-center gap-2 rounded-xl border border-line p-2 pl-3">
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium">{user?.name || user?.email.split("@")[0]}</div>
            <div className="truncate text-xs text-muted">{user?.email}</div>
          </div>
          <IconButton onClick={logout} aria-label="Sair" title="Sair"><LogOut className="size-4" /></IconButton>
        </div>
      </div>
    </>
  );

  return (
    <div className="flex h-full">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-line bg-surface p-3 pt-5 lg:flex">{nav}</aside>

      {open && <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={close} />}
      <aside
        className={cx(
          "fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-line bg-surface p-3 pt-5 transition-transform lg:hidden",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <IconButton className="absolute right-3 top-4" onClick={close} aria-label="Fechar menu"><X className="size-4" /></IconButton>
        {nav}
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-line bg-surface px-4 py-3 lg:hidden">
          <IconButton onClick={() => setOpen(true)} aria-label="Abrir menu"><Menu className="size-5" /></IconButton>
          <Logo name={appName} />
        </header>
        <main key={loc.pathname} className="min-h-0 flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-[22px] font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  );
}
