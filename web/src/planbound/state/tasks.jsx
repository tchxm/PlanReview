import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../../api";

// A cache of what the BACKEND returned. Nothing here decides verdicts, hashes,
// gate results or audit records; it only stores and refreshes them.
const Ctx = createContext(null);
export const useTasks = () => useContext(Ctx);

export function TasksProvider({ children }) {
  const [tasks, setTasks] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(null);
  const [health, setHealth] = useState(null);
  const [backend, setBackend] = useState("checking");
  const seq = useRef(0);

  const refresh = useCallback(async () => {
    const mine = ++seq.current;
    try {
      const [list, h] = await Promise.all([api.listTasks(), api.health()]);
      if (mine !== seq.current) return list;
      setTasks(list || []);
      setHealth(h);
      setBackend("online");
      setError(null);
      setLoaded(true);
      return list;
    } catch (e) {
      if (mine === seq.current) {
        setError(e instanceof ApiError ? e : new ApiError("NETWORK_ERROR", String(e?.message || e)));
        setBackend(["BACKEND_UNAVAILABLE", "NETWORK_ERROR", "TIMEOUT"].includes(e?.code) ? "offline" : "online");
        setLoaded(true);
      }
      return null;
    }
  }, []);

  useEffect(() => {
    refresh();
    const onFocus = () => refresh();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [refresh]);

  const upsert = useCallback((task) => {
    setTasks((ts) => {
      const i = ts.findIndex((t) => t.id === task.id);
      if (i === -1) return [task, ...ts];
      const next = ts.slice();
      next[i] = task;
      return next;
    });
    return task;
  }, []);

  const value = useMemo(() => ({ tasks, loaded, error, health, backend, refresh, upsert }), [tasks, loaded, error, health, backend, refresh, upsert]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** One task, from the cache or fetched from the backend. */
export function useTask(id) {
  const { tasks, loaded, upsert } = useTasks();
  const cached = tasks.find((t) => t.id === id) || null;
  const [state, setState] = useState({ loading: false, error: null });
  const tried = useRef(null);
  const load = useCallback(async () => {
    setState({ loading: true, error: null });
    try {
      upsert(await api.getTask(id));
      setState({ loading: false, error: null });
    } catch (e) {
      setState({ loading: false, error: e });
    }
  }, [id, upsert]);
  useEffect(() => {
    if (!loaded || cached || tried.current === id) return;
    tried.current = id;
    load();
  }, [loaded, cached, id, load]);
  return { task: cached, loading: state.loading || !loaded, error: state.error, reload: load };
}
