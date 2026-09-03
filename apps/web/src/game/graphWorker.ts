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
//
// graph-expansion Phase 1: a successful response's four large CSR arrays
// (`node_ids`/`offsets`/`neighbors`/`evidence_release_ids`, now real
// `Int32Array`s per `validatePathfindingGraph`) are handed to `postMessage`
// as Transferable `ArrayBuffer`s (`postGraphSuccess` below) instead of
// letting the structured-clone algorithm copy them -- a real, separate
// memory/transfer-cost win from the role-dictionary encoding change
// (ADR 0071), which only shrank the wire payload.

import {
  validatePathfindingGraph,
  type PathfindingGraph,
} from "./pathfindingGraph";

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
  | {
      id: number;
      ok: true;
      graph: unknown;
      rawText: string;
      /** Wall-clock ms spent parsing + canonicalizing + hashing (the
       * `validatePathfindingGraph` integrity check), excluding the network
       * fetch -- `docs/SITE_REPROFILE_METHOD.md`'s own documented gap: this
       * is the ~405ms/~535ms cost ADR 0059 Phase 5c moved off the main
       * thread, previously unobservable from outside the worker at all. */
      parseMs: number;
    }
  | {
      id: number;
      ok: false;
      error: "fetch-failed" | "parse-failed" | "invalid-graph";
    };

interface WorkerSelf {
  postMessage(message: GraphWorkerResponse, transfer?: Transferable[]): void;
  onmessage: ((event: { data: GraphWorkerRequest }) => void) | null;
}

const workerSelf = self as unknown as WorkerSelf;

workerSelf.onmessage = (event) => {
  void handleRequest(event.data);
};

/** Posts a successful response with `node_ids`/`offsets`/`neighbors`/
 * `evidence_release_ids` transferred as zero-copy `ArrayBuffer`s (graph-
 * expansion Phase 1) rather than structured-cloned -- each of the four
 * `Int32Array`s `validatePathfindingGraph` returns owns its own distinct
 * buffer (built via separate `Int32Array.from` calls), so listing all four
 * is safe: no aliasing, no buffer shared with anything the worker still
 * needs after this call. Transferring detaches these buffers on the
 * worker's side, which is fine -- `graph` is never reused past this one
 * response. */
function postGraphSuccess(
  id: number,
  graph: PathfindingGraph,
  rawText: string,
  parseMs: number,
): void {
  workerSelf.postMessage({ id, ok: true, graph, rawText, parseMs }, [
    graph.node_ids.buffer,
    graph.offsets.buffer,
    graph.neighbors.buffer,
    graph.evidence_release_ids.buffer,
  ]);
}

async function handleRequest(request: GraphWorkerRequest): Promise<void> {
  const { id, url, cachedText } = request;

  if (cachedText) {
    try {
      const parseStart = performance.now();
      const graph = await validatePathfindingGraph(JSON.parse(cachedText));
      const parseMs = performance.now() - parseStart;
      if (graph) {
        postGraphSuccess(id, graph, cachedText, parseMs);
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

  const parseStart = performance.now();
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    workerSelf.postMessage({ id, ok: false, error: "parse-failed" });
    return;
  }

  const graph = await validatePathfindingGraph(raw);
  const parseMs = performance.now() - parseStart;
  if (!graph) {
    workerSelf.postMessage({ id, ok: false, error: "invalid-graph" });
    return;
  }
  postGraphSuccess(id, graph, text, parseMs);
}
