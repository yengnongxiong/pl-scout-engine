import { useState } from "react";

import type { Schemas } from "../api/client";
import { useTeamSearch } from "../hooks/teams";
import { useDebounced } from "../hooks/useDebounced";
import { Combobox } from "./Combobox";

type Hit = Schemas["TeamSearchHit"];

/** Club search with aliases ("Spurs", "Man City") and suggestions for typos (US-01). */
export function ClubPicker({
  onSelect,
  label = "Club",
}: {
  onSelect: (hit: Hit) => void;
  label?: string;
}) {
  const [query, setQuery] = useState("");
  const search = useTeamSearch(useDebounced(query));
  const hits = search.data ?? [];
  const fuzzy = hits.length > 0 && hits.every((h) => h.kind === "fuzzy");
  return (
    <Combobox
      label={label}
      placeholder="Type a club name or nickname, e.g. Spurs"
      query={query}
      onQueryChange={setQuery}
      items={hits}
      getKey={(h) => h.team_id}
      isLoading={search.isFetching}
      isError={search.isError}
      emptyText="No club matches. Check the spelling."
      hint={fuzzy ? "No exact match. Did you mean one of these?" : undefined}
      onSelect={(hit) => {
        setQuery(hit.name);
        onSelect(hit);
      }}
      renderItem={(h) => (
        <span className="flex justify-between gap-2">
          <span>{h.name}</span>
          {h.matched !== h.name ? (
            <span className="text-xs text-slate-600">matched “{h.matched}”</span>
          ) : null}
        </span>
      )}
    />
  );
}
