// Types for the game universe and round artifacts (docs/WEB_PRODUCT_PLAN.md §8)
// and the client round engine (§5). The JSON contracts are documented in
// data/contracts/game-universe-v1.md and data/contracts/game-rounds-v1.md;
// scripts/build-rounds.mjs derives and validates the artifacts at build time.

export type RoleCategory =
  | "bass"
  | "drums"
  | "guitar"
  | "keys"
  | "organ"
  | "percussion"
  | "sax"
  | "trumpet"
  | "violin"
  | "flute"
  | "harp"
  | "backing_vocals"
  | "string_arrangement"
  | "producer"
  | "engineer"
  | "mixing"
  | "mastering";

export interface SyntheticProvenance {
  source: string;
  license: string;
  note: string;
  generated_by: string;
}

export type SleeveArt =
  | { kind: "generated" }
  | { kind: "hotlink"; uri150: string; uri: string }
  | null;

export interface GameAlbum {
  id: string;
  title: string;
  act: string;
  act_id: number;
  year: number;
  label: string;
  art: SleeveArt;
}

export interface GameContributor {
  id: number;
  name: string;
  role_category: RoleCategory;
  performer: boolean;
}

export interface GameRelease {
  id: string;
  album_id: string;
  title: string;
  year: number;
  catalog_stamp: string;
}

export interface GameCredit {
  release_id: string;
  contributor_id: number;
  role_text: string;
  role_category: RoleCategory;
  credit_scope: "release_credit";
}

export interface GameUniverse {
  schema_version: 1;
  provenance: SyntheticProvenance;
  albums: GameAlbum[];
  contributors: GameContributor[];
  releases: GameRelease[];
  credits: GameCredit[];
}

export type RoundPool = "synthetic-universe" | "real-records";
export type RoundKind = "one_hop" | "two_hop";
export type RoundDifficulty = "easy" | "medium" | "hard";

export interface AlbumRef {
  id: string;
  title: string;
  year: number | null;
  act: string | null;
  /** Fictional label for synthetic albums (drives generated sleeve style); null for real records. */
  label: string | null;
  art: SleeveArt;
}

export interface ContributorRef {
  id: number;
  name: string;
  role_category: string;
}

export interface Clue {
  kind: "years" | "role" | "initials" | "credit_excerpt" | "eliminate";
  text: string;
  eliminate_ids?: number[];
}

export interface EvidenceRow {
  release_ref: string;
  release_title: string;
  contributor_id: number;
  credited_as: string;
  role_text: string;
  credit_scope: string;
}

export interface GameRound {
  id: string;
  pool: RoundPool;
  kind: RoundKind;
  difficulty: RoundDifficulty;
  endpoints: [AlbumRef, AlbumRef];
  middle?: { album: AlbumRef; choices: AlbumRef[] };
  answer_set: ContributorRef[];
  bridge_answer_sets?: [ContributorRef[], ContributorRef[]];
  distractors: ContributorRef[];
  clues: Clue[];
  evidence: EvidenceRow[];
  provenance_note: string;
}

export interface GameRounds {
  schema_version: 1;
  provenance: SyntheticProvenance;
  rounds: GameRound[];
}

// --- Engine state (docs/WEB_PRODUCT_PLAN.md §5 state machine) ---

export type Phase = "idle" | "dealing" | "guessing" | "resolving" | "revealed";

/** Which question the player is currently answering within the round. */
export type Step = "single" | "bridge_a" | "bridge_b" | "middle";

export type Rating = "clean" | "with_clues" | "revealed";

export interface EngineState {
  phase: Phase;
  step: Step;
  attemptsLeft: number;
  cluesUsed: number;
  struck: number[];
  /** Album ids struck from the middle choices (two-hop beat 2). */
  struckAlbums: string[];
  solvedSteps: Step[];
  solved: boolean;
  failed: boolean;
  rating: Rating | null;
}
