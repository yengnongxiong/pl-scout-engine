import { Route, Routes } from "react-router";

import { Layout } from "./components/Layout";
import { EmptyState } from "./components/states";

function Placeholder({ title }: { title: string }) {
  return (
    <section>
      <h1 className="text-2xl font-semibold">{title}</h1>
      <EmptyState title="Coming in M8">This page is built in milestone M8 (PRD §16).</EmptyState>
    </section>
  );
}

export function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Placeholder title="Club diagnosis" />} />
        <Route path="/methodology" element={<Placeholder title="Methodology & data" />} />
        <Route path="*" element={<Placeholder title="Page not found" />} />
      </Routes>
    </Layout>
  );
}
