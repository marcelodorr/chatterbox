import { useCallback, useEffect, useState } from "react";
import { History as HistoryIcon, Trash2 } from "lucide-react";
import { api, type Generation, formatDate, waitForGeneration } from "../lib/api";
import { useToast } from "../lib/toast";
import { PageHeader } from "../components/Layout";
import { Button, Empty, IconButton, Spinner } from "../components/ui";
import { GenerationRow } from "./TextToSpeech";

const PAGE = 30;

export default function History() {
  const toast = useToast();
  const [items, setItems] = useState<Generation[] | null>(null);
  const [more, setMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  const fetchPage = useCallback(async (before?: number) => {
    const qs = new URLSearchParams({ limit: String(PAGE) });
    if (before) qs.set("before", String(before));
    const { generations } = await api.get<{ generations: Generation[] }>(`/api/generations?${qs}`);
    setMore(generations.length === PAGE);
    return generations;
  }, []);

  useEffect(() => {
    fetchPage().then((list) => {
      setItems(list);
      const update = (g: Generation) => setItems((l) => l?.map((x) => (x.id === g.id ? g : x)) ?? l);
      list.filter((g) => g.status === "queued" || g.status === "running").forEach((g) => waitForGeneration(g.id, update).catch(() => {}));
    });
  }, [fetchPage]);

  const loadMore = async () => {
    if (!items?.length) return;
    setLoadingMore(true);
    const list = await fetchPage(items[items.length - 1].created_at);
    setItems([...items, ...list]);
    setLoadingMore(false);
  };

  const remove = async (g: Generation) => {
    try {
      await api.del(`/api/generations/${g.id}`);
      setItems((l) => l?.filter((x) => x.id !== g.id) ?? l);
    } catch (e) {
      toast("error", (e as Error).message);
    }
  };

  // agrupa por dia
  const groups: [string, Generation[]][] = [];
  for (const g of items ?? []) {
    const day = new Date(g.created_at * 1000).toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" });
    const last = groups[groups.length - 1];
    if (last && last[0] === day) last[1].push(g);
    else groups.push([day, [g]]);
  }

  return (
    <div className="mx-auto max-w-4xl p-4 sm:p-6 lg:p-8">
      <PageHeader title="Histórico" subtitle="Todas as suas gerações, incluindo as feitas pelo Claude e pelo ChatGPT." />
      {items === null ? (
        <div className="flex justify-center py-16"><Spinner /></div>
      ) : items.length === 0 ? (
        <Empty icon={<HistoryIcon className="size-5" />} title="Nada por aqui ainda">Gere seu primeiro áudio em Texto para fala.</Empty>
      ) : (
        <div className="flex flex-col gap-6">
          {groups.map(([day, list]) => (
            <section key={day}>
              <h2 className="mb-2 text-xs font-medium uppercase tracking-wider text-faint">{day}</h2>
              <div className="flex flex-col gap-2">
                {list.map((g) => (
                  <GenerationRow
                    key={g.id}
                    g={g}
                    actions={
                      <div className="flex shrink-0 flex-col items-end gap-1">
                        <span className="text-xs text-faint">{formatDate(g.created_at).split(", ").pop()}</span>
                        {g.status !== "queued" && g.status !== "running" && (
                          <IconButton onClick={() => remove(g)} aria-label="Excluir" title="Excluir"><Trash2 className="size-4" /></IconButton>
                        )}
                      </div>
                    }
                  />
                ))}
              </div>
            </section>
          ))}
          {more && (
            <Button className="self-center" onClick={loadMore} loading={loadingMore}>Carregar mais</Button>
          )}
        </div>
      )}
    </div>
  );
}
