import { useEffect, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Loader2, X } from "lucide-react";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
};

export function Button({ variant = "secondary", size = "md", loading, className, children, disabled, ...rest }: BtnProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-full font-medium transition-colors whitespace-nowrap",
        "focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[var(--ring)] disabled:opacity-50 disabled:cursor-not-allowed",
        size === "sm" && "h-8 px-3 text-[13px]",
        size === "md" && "h-10 px-4 text-sm",
        size === "lg" && "h-11 px-5 text-[15px]",
        variant === "primary" && "bg-accent text-accent-fg hover:opacity-90",
        variant === "secondary" && "border border-line bg-surface hover:bg-surface-2",
        variant === "ghost" && "hover:bg-surface-2 text-muted hover:text-fg",
        variant === "danger" && "border border-line bg-surface text-danger hover:bg-surface-2",
        className,
      )}
    >
      {loading && <Loader2 className="size-4 animate-spin" />}
      {children}
    </button>
  );
}

export function IconButton({ className, children, ...rest }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...rest}
      className={cx(
        "inline-flex size-8 items-center justify-center rounded-full text-muted hover:bg-surface-2 hover:text-fg transition-colors",
        "focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[var(--ring)] disabled:opacity-40",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cx("rounded-2xl border border-line bg-surface", className)}>{children}</div>;
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "ok" | "warn" | "error" }) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11.5px] font-medium",
        tone === "neutral" && "bg-surface-2 text-muted",
        tone === "ok" && "bg-[color-mix(in_oklab,var(--ok)_14%,transparent)] text-ok",
        tone === "warn" && "bg-[color-mix(in_oklab,#d9a400_16%,transparent)] text-[#a07800] dark:text-[#e6c24d]",
        tone === "error" && "bg-[color-mix(in_oklab,var(--danger)_14%,transparent)] text-danger",
      )}
    >
      {children}
    </span>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-medium">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

export const inputCls =
  "w-full h-10 rounded-xl border border-line bg-surface px-3 text-sm outline-none transition-shadow placeholder:text-faint focus:ring-4 focus:ring-[var(--ring)]";

export function Slider({
  label, value, min, max, step, onChange, left, right,
}: {
  label: string; value: number; min: number; max: number; step: number;
  onChange: (v: number) => void; left?: string; right?: string;
}) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-[13px]">
        <span className="font-medium">{label}</span>
        <span className="tabular-nums text-muted">{value.toFixed(2)}</span>
      </div>
      <input
        type="range" min={min} max={max} step={step} value={value}
        style={{ ["--pct" as string]: `${pct}%` }}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        aria-label={label}
      />
      {(left || right) && (
        <div className="mt-0.5 flex justify-between text-[11.5px] text-faint">
          <span>{left}</span>
          <span>{right}</span>
        </div>
      )}
    </div>
  );
}

export function Modal({ open, onClose, title, children, wide }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex items-end sm:items-center justify-center bg-black/40 p-0 sm:p-4" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(e) => e.stopPropagation()}
        className={cx(
          "w-full max-h-[92vh] overflow-y-auto rounded-t-2xl sm:rounded-2xl border border-line bg-surface shadow-2xl",
          wide ? "sm:max-w-2xl" : "sm:max-w-md",
        )}
      >
        <div className="flex items-center justify-between px-5 pt-5 pb-2">
          <h2 className="text-[17px] font-semibold">{title}</h2>
          <IconButton onClick={onClose} aria-label="Fechar"><X className="size-4" /></IconButton>
        </div>
        <div className="px-5 pb-5">{children}</div>
      </div>
    </div>
  );
}

/** Avatar com gradiente determinístico a partir do id da voz. */
export function VoiceAvatar({ id, size = 36 }: { id: string; size?: number }) {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  const a = h % 360;
  const b = (a + 40 + (h % 80)) % 360;
  return (
    <div
      className="shrink-0 rounded-full"
      style={{
        width: size, height: size,
        background: `radial-gradient(circle at 30% 25%, hsl(${a} 85% 72%), hsl(${b} 70% 48%))`,
      }}
    />
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx("size-4 animate-spin", className)} />;
}

export function Equalizer() {
  return (
    <span className="eq inline-flex h-3.5 items-end gap-[2px]" aria-hidden>
      <span className="h-full" /><span className="h-full" /><span className="h-full" /><span className="h-full" />
    </span>
  );
}

export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-14 text-center">
      <div className="mb-1 flex size-11 items-center justify-center rounded-full bg-surface-2 text-muted">{icon}</div>
      <p className="font-medium">{title}</p>
      {children && <div className="max-w-sm text-sm text-muted">{children}</div>}
    </div>
  );
}
