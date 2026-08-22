/**
 * Domain shapes mirrored from the D5 FastAPI backend (the JSON shape of a cited
 * RecommendationSet produced by `to_jsonable`).
 */

export type Market = "JP" | "AU" | "SG";
export type Vertical = "banking" | "online_retail";

export interface Citation {
  source_id: string;
  source_type: string;
  title: string;
  url?: string;
  page?: number | null;
  published_date?: string | null;
  snippet?: string;
  score?: number | null;
}

export interface EligibilityResult {
  offer_id: string;
  outcome: string;
  reasons: string[];
  failed_rule_ids: string[];
  citations: Citation[];
}

export interface ConsentDecision {
  offer_id: string;
  allowed: boolean;
  channel?: string | null;
  reason?: string;
  citation?: Citation | null;
}

export interface Recommendation {
  offer_id: string;
  name: string;
  kind: string;
  rank: number;
  score: number;
  propensity: number;
  value_score: number;
  channel?: string | null;
  eligibility: EligibilityResult;
  consent: ConsentDecision;
  explanation?: string;
  citations: Citation[];
}

export interface RecommendationSet {
  id: string;
  customer_id: string;
  market: Market;
  vertical: Vertical;
  recommendations: Recommendation[];
  suppressed: EligibilityResult[];
  consent_suppressed: ConsentDecision[];
  summary: string;
  citations: Citation[];
  requires_human_review: boolean;
}

export interface Health {
  status: string;
  profile: string;
  market: string;
  vertical: string;
}

// A seeded dev persona (local profile only), listed by GET /v1/personas for the picker.
// The chosen id is sent back as the X-Dev-Persona header; the backend resolves a verified
// Principal from it (there is no client-asserted actor).
export interface Persona {
  id: string;
  subject: string;
  tenant: string;
  principals: string;
}
