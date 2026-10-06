import { setupServer } from "msw/node";

import { handlers } from "./handlers.synthetic";

/** MSW server: no real network in front-end tests (CLAUDE.md testing rules). */
export const server = setupServer(...handlers);
