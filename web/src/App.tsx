import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router";

import { Layout } from "./components/Layout";
import { EmptyState, LoadingState } from "./components/states";

// Route-level code splitting keeps the first load small (PRD §14: < 2 s locally).
const DiagnosisPage = lazy(() =>
  import("./pages/DiagnosisPage").then((m) => ({ default: m.DiagnosisPage })),
);
const ShortlistPage = lazy(() =>
  import("./pages/ShortlistPage").then((m) => ({ default: m.ShortlistPage })),
);
const PlayerPage = lazy(() =>
  import("./pages/PlayerPage").then((m) => ({ default: m.PlayerPage })),
);
const ComparePage = lazy(() =>
  import("./pages/ComparePage").then((m) => ({ default: m.ComparePage })),
);
const MethodologyPage = lazy(() =>
  import("./pages/MethodologyPage").then((m) => ({ default: m.MethodologyPage })),
);

function NotFound() {
  return (
    <section>
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <EmptyState title="Not available">There is no page at this address.</EmptyState>
    </section>
  );
}

export function App() {
  return (
    <Layout>
      <Suspense fallback={<LoadingState label="Loading page…" />}>
        <Routes>
          <Route path="/" element={<DiagnosisPage />} />
          <Route path="/clubs/:teamId/needs/:needId" element={<ShortlistPage />} />
          <Route path="/players/:playerId" element={<PlayerPage />} />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/methodology" element={<MethodologyPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
    </Layout>
  );
}
