import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "./index.css";
import { AuthProvider, useAuth } from "./lib/auth";
import { ToastProvider } from "./lib/toast";
import { Layout } from "./components/Layout";
import { Spinner } from "./components/ui";
import Login from "./pages/Login";
import TextToSpeech from "./pages/TextToSpeech";
import Voices from "./pages/Voices";
import History from "./pages/History";
import Integrations from "./pages/Integrations";
import Users from "./pages/Users";

function Protected() {
  const { user, loading } = useAuth();
  if (loading) {
    return <div className="flex h-full items-center justify-center"><Spinner /></div>;
  }
  if (!user) {
    const next = window.location.pathname + window.location.search;
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />;
  }
  return <Layout />;
}

function App() {
  const { loading } = useAuth();
  if (loading) return <div className="flex h-full items-center justify-center"><Spinner /></div>;
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Protected />}>
        <Route path="/tts" element={<TextToSpeech />} />
        <Route path="/voices" element={<Voices />} />
        <Route path="/history" element={<History />} />
        <Route path="/integrations" element={<Integrations />} />
        <Route path="/users" element={<Users />} />
      </Route>
      <Route path="*" element={<Navigate to="/tts" replace />} />
    </Routes>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
