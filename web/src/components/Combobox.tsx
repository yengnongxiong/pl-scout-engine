import { useId, useState, type KeyboardEvent, type ReactNode } from "react";

interface ComboboxProps<T> {
  label: string;
  placeholder?: string;
  query: string;
  onQueryChange: (q: string) => void;
  items: readonly T[];
  getKey: (item: T) => string | number;
  renderItem: (item: T) => ReactNode;
  onSelect: (item: T) => void;
  isLoading?: boolean;
  isError?: boolean;
  emptyText: string;
  hint?: ReactNode;
}

/**
 * Accessible combobox (WAI-ARIA 1.2 list autocomplete): type to search, arrow keys to move,
 * Enter to choose, Escape to close. Suggestions come from the API; nothing is filtered here.
 */
export function Combobox<T>({
  label,
  placeholder,
  query,
  onQueryChange,
  items,
  getKey,
  renderItem,
  onSelect,
  isLoading = false,
  isError = false,
  emptyText,
  hint,
}: ComboboxProps<T>) {
  const id = useId();
  const listId = `${id}-list`;
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const showList = open && query.trim().length > 0;
  const activeItem = items[active];

  function choose(item: T) {
    onSelect(item);
    setOpen(false);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(i + 1, Math.max(items.length - 1, 0)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (event.key === "Enter") {
      if (showList && activeItem !== undefined) {
        event.preventDefault();
        choose(activeItem);
      }
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className="relative">
      <label htmlFor={id} className="block text-sm font-medium text-slate-700">
        {label}
      </label>
      <input
        id={id}
        type="text"
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={
          showList && activeItem !== undefined
            ? `${id}-opt-${String(getKey(activeItem))}`
            : undefined
        }
        autoComplete="off"
        placeholder={placeholder}
        value={query}
        onChange={(event) => {
          onQueryChange(event.target.value);
          setActive(0);
          setOpen(true);
        }}
        onFocus={() => {
          setOpen(true);
        }}
        onBlur={() => {
          setOpen(false);
        }}
        onKeyDown={onKeyDown}
        className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-accent-600 focus:ring-2 focus:ring-accent-600 focus:outline-none"
      />
      {hint ? <p className="mt-1 text-xs text-slate-600">{hint}</p> : null}
      <ul
        id={listId}
        role="listbox"
        aria-label={`${label} suggestions`}
        hidden={!showList}
        className="absolute z-10 mt-1 max-h-72 w-full overflow-auto rounded-md border border-slate-200 bg-white py-1 text-sm shadow-lg"
      >
        {showList && isError ? (
          <li className="px-3 py-2 text-red-800" role="presentation">
            Search is unavailable right now.
          </li>
        ) : null}
        {showList && !isError && isLoading && items.length === 0 ? (
          <li className="px-3 py-2 text-slate-600" role="presentation">
            Searching…
          </li>
        ) : null}
        {showList && !isError && !isLoading && items.length === 0 ? (
          <li className="px-3 py-2 text-slate-600" role="presentation">
            {emptyText}
          </li>
        ) : null}
        {showList
          ? items.map((item, index) => (
              <li
                key={getKey(item)}
                id={`${id}-opt-${String(getKey(item))}`}
                role="option"
                aria-selected={index === active}
                onMouseDown={(event) => {
                  event.preventDefault();
                  choose(item);
                }}
                onMouseEnter={() => {
                  setActive(index);
                }}
                className={`cursor-pointer px-3 py-2 ${index === active ? "bg-accent-50 text-accent-800" : "text-slate-800"}`}
              >
                {renderItem(item)}
              </li>
            ))
          : null}
      </ul>
    </div>
  );
}
