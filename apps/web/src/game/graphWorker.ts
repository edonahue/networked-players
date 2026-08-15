// Off-main-thread parse + canonical-stringify + SHA-256 for the pathfinding
// graph artifact (ADR 0059 Phase 5 PR 5c). Justified by measurement, not
// preference: profiling this exact pipeline on this machine found ~405ms of
// ~535ms total main-thread work is parse+canonicalize+hash (the integrity
// check `validatePathfindingGraph` performs, recomputing
// `pathfinding_graph_version` from content) -- moving that off the main
// thread keeps the page responsive during a cold graph load instead of
// janking for most of a second. Bounded scope, per ADR 0059's own risk
// note: this worker ONLY fetches, parses, and validates/hashes; no BFS or
// ranking logic moves off-thread, and the hash is never skipped or
// deferred past validation -- a failed validation is still reported as
// `invalid-graph`, exactly like the main-thread path it replaces.
//
// Typed via a local, minimal `self` shape rather than the ambient
// "webworker" lib: this project's single shared tsconfig already includes
// "dom" (every other file in `apps/web/src` needs it), and TypeScript
// doesn't support mixing "dom" and "webworker" lib globals in one
// compilation -- both declare conflicting types for `self`/`postMessage`.
// Casting once here, for exactly the two worker APIs this file uses,
// avoids a second tsconfig just for one file.

import { validatePathfindingGraph } from "./pathfindingGraph";

export interface GraphWorkerRequest {
  id: number;
  url: string;
  /** A previously-cached raw JSON string (from the main thread's
   * `sessionStorage`, which a worker has no access to), if any --
   * validated in place instead of fetching, mirroring the main-thread
   * loader's own cache-first order. */
  cachedText: string | null;
}

export type GraphWorkerResponse =
  | { id: number; ok: true; graph: unknown; rawText: string }
  | {
      id: number;
      ok: false;
      error: "fetch-failed" | "parse-failed" | "invalid-graph";
    };

interface WorkerSelf {
  postMessage(message: GraphWorkerResponse): void;
  onmessage: ((event: { data: GraphWorkerRequest }) => void) | null;
}

const workerSelf = self as unknown as WorkerSelf;

workerSelf.onmessage = (event) => {
  void handleRequest(event.data);
};

async function handleRequest(request: GraphWorkerRequest): Promise<void> {
  const { id, url, cachedText } = request;

  if (cachedText) {
    try {
      const graph = await validatePathfindingGraph(JSON.parse(cachedText));
      if (graph) {
        workerSelf.postMessage({ id, ok: true, graph, rawText: cachedText });
        return;
      }
    } catch {
      // Fall through to a fresh fetch -- a corrupted cache entry is not
      // itself a fetch failure.
    }
  }

  let response: Response;
  try {
    response = await fetch(url);
  } catch {
    workerSelf.postMessage({ id, ok: false, error: "fetch-failed" });
    return;
  }
  if (!response.ok) {
    workerSelf.postMessage({ id, ok: false, error: "fetch-failed" });
    return;
  }

  let text: string;
  try {
    text = await response.text();
  } catch {
    workerSelf.postMessage({ id, ok: false, error: "parse-failed" });
    return;
  }

  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    workerSelf.postMessage({ id, ok: false, error: "parse-failed" });
    return;
  }

  const graph = await validatePathfindingGraph(raw);
  if (!graph) {
    workerSelf.postMessage({ id, ok: false, error: "invalid-graph" });
    return;
  }
  workerSelf.postMessage({ id, ok: true, graph, rawText: text });
}
