import { useEffect, useRef, useState } from "react";
import { Download, Pause, Play } from "lucide-react";
import { formatDuration } from "../lib/api";
import { IconButton } from "./ui";

// Só um player toca por vez.
let current: HTMLAudioElement | null = null;

export function AudioPlayer({
  src, downloadName, autoPlay, compact,
}: { src: string; downloadName?: string; autoPlay?: boolean; compact?: boolean }) {
  const ref = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [dur, setDur] = useState(0);

  useEffect(() => {
    const a = ref.current;
    if (!a) return;
    const onTime = () => setTime(a.currentTime);
    const onMeta = () => setDur(a.duration);
    const onPlay = () => {
      if (current && current !== a) current.pause();
      current = a;
      setPlaying(true);
    };
    const onPause = () => setPlaying(false);
    a.addEventListener("timeupdate", onTime);
    a.addEventListener("loadedmetadata", onMeta);
    a.addEventListener("play", onPlay);
    a.addEventListener("pause", onPause);
    a.addEventListener("ended", onPause);
    if (autoPlay) a.play().catch(() => {});
    return () => {
      a.removeEventListener("timeupdate", onTime);
      a.removeEventListener("loadedmetadata", onMeta);
      a.removeEventListener("play", onPlay);
      a.removeEventListener("pause", onPause);
      a.removeEventListener("ended", onPause);
    };
  }, [src, autoPlay]);

  const toggle = () => {
    const a = ref.current;
    if (!a) return;
    if (a.paused) a.play();
    else a.pause();
  };

  const seek = (e: React.MouseEvent<HTMLDivElement>) => {
    const a = ref.current;
    if (!a || !dur) return;
    const rect = e.currentTarget.getBoundingClientRect();
    a.currentTime = ((e.clientX - rect.left) / rect.width) * dur;
  };

  const pct = dur ? (time / dur) * 100 : 0;

  return (
    <div className="flex items-center gap-2.5 min-w-0">
      <audio ref={ref} src={src} preload="metadata" />
      <button
        onClick={toggle}
        aria-label={playing ? "Pausar" : "Tocar"}
        className="flex size-8 shrink-0 items-center justify-center rounded-full bg-accent text-accent-fg hover:opacity-90"
      >
        {playing ? <Pause className="size-3.5" fill="currentColor" /> : <Play className="size-3.5 translate-x-px" fill="currentColor" />}
      </button>
      <div className="group relative h-6 flex-1 min-w-12 cursor-pointer flex items-center" onClick={seek}>
        <div className="h-1 w-full rounded-full bg-line overflow-hidden">
          <div className="h-full bg-fg transition-[width] duration-100" style={{ width: `${pct}%` }} />
        </div>
      </div>
      {!compact && (
        <span className="w-[76px] shrink-0 text-right text-xs tabular-nums text-muted">
          {formatDuration(time)} / {formatDuration(dur)}
        </span>
      )}
      {downloadName && (
        <a
          href={`${src}${src.includes("?") ? "&" : "?"}download=1`}
          download={downloadName}
          aria-label="Baixar"
          title="Baixar WAV"
          className="inline-flex size-8 shrink-0 items-center justify-center rounded-full text-muted hover:bg-surface-2 hover:text-fg"
        >
          <Download className="size-4" />
        </a>
      )}
    </div>
  );
}

/** Botão simples de prévia (play/pause) usado em listas de vozes. */
export function PreviewButton({ src }: { src: string }) {
  const ref = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(false);
  useEffect(() => () => ref.current?.pause(), []);
  const toggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!ref.current) {
      ref.current = new Audio(src);
      ref.current.addEventListener("ended", () => setPlaying(false));
      ref.current.addEventListener("pause", () => setPlaying(false));
      ref.current.addEventListener("play", () => {
        if (current && current !== ref.current) current.pause();
        current = ref.current;
        setPlaying(true);
      });
    }
    if (ref.current.paused) ref.current.play();
    else ref.current.pause();
  };
  return (
    <IconButton onClick={toggle} aria-label={playing ? "Pausar amostra" : "Ouvir amostra"}>
      {playing ? <Pause className="size-4" fill="currentColor" /> : <Play className="size-4" fill="currentColor" />}
    </IconButton>
  );
}
