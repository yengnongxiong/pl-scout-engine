import { useState } from "react";

import type { Schemas } from "../api/client";
import { usePlayerSearch } from "../hooks/players";
import { useDebounced } from "../hooks/useDebounced";
import { positionLabel } from "../lib/labels";
import { Combobox } from "./Combobox";

type Hit = Schemas["PlayerSearchHit"];

/** Player search by any part of the name, with suggestions for typos. */
export function PlayerPicker({ onSelect, label }: { onSelect: (hit: Hit) => void; label: string }) {
  const [query, setQuery] = useState("");
  const search = usePlayerSearch(useDebounced(query));
  return (
    <Combobox
      label={label}
      placeholder="Type a player name"
      query={query}
      onQueryChange={setQuery}
      items={search.data ?? []}
      getKey={(h) => h.player_id}
      isLoading={search.isFetching}
      isError={search.isError}
      emptyText="No player matches."
      onSelect={(hit) => {
        setQuery(hit.name);
        onSelect(hit);
      }}
      renderItem={(h) => (
        <span className="flex justify-between gap-2">
          <span>{h.name}</span>
          <span className="text-xs text-slate-600">
            {h.team_name} · {positionLabel(h.position_group)}
          </span>
        </span>
      )}
    />
  );
}
