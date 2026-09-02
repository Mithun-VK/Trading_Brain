// Mirrors apps/api/schemas.py and the brain/*/schemas.py Pydantic models.
// Keep these in sync by hand -- there is no shared codegen in this phase.

// Liveness (/health/live) only. Aggregate health is `HealthOut`, below.
export interface LivenessOut {
  status: string;
  app_env: string;
}

export interface AssetOut {
  ticker: string;
  exchange: string;
  asset_type: string;
  name: string;
  currency: string;
  sector: string | null;
  industry: string | null;
}

export interface QuoteOut {
  ticker: string;
  price: number;
  change: number;
  change_percent: number;
  volume: number;
  as_of: string;
  source: string;
}

export interface AnalysisOut {
  ticker: string;
  quant_summary: Record<string, unknown>;
  market_regime: Record<string, string> | null;
}

export interface MarketRegimeOut {
  observed_at: string;
  scope: string;
  trend_regime: string;
  volatility_regime: string;
  risk_regime: string;
}

export interface ResearchAnalysis {
  ticker: string;
  summary: string;
  positive_factors: string[];
  negative_factors: string[];
  contradictions: string[];
  risks: string[];
  catalysts: string[];
  confidence: number;
  source_notes: string[];
}

export interface ThesisOut {
  id: number;
  ticker: string;
  title: string;
  status: string;
  current_assessment: string;
  conviction: string | null;
  time_horizon: string | null;
  last_reviewed_at: string | null;
}

export interface ThesisReview {
  thesis_id: number;
  ticker: string;
  previous_assessment: string;
  assessment: string;
  reasoning: string;
  supporting_evidence: string[];
  contradicting_evidence: string[];
  changed_assumptions: string[];
  invalidation_conditions_triggered: string[];
  confidence: number;
  reviewed_at: string;
}

export interface TradeOut {
  id: number;
  ticker: string;
  direction: string;
  timeframe: string;
  entry_price: number;
  stop_price: number;
  target_price: number | null;
  risk_amount: number;
  position_size: number;
  r_multiple: number | null;
  status: string;
  result: string | null;
  market_regime: string | null;
  opened_at: string;
  closed_at: string | null;
}

export interface TradeIn {
  ticker: string;
  direction: string;
  strategy_name?: string;
  timeframe: string;
  entry_price: number;
  stop_price: number;
  target_price?: number;
  risk_amount: number;
  position_size: number;
  market_regime?: string;
  opened_at: string;
}

export interface GroupStats {
  label: string;
  trade_count: number;
  win_rate: number;
  profit_factor: number;
  expectancy_r: number;
  average_winner_r: number;
  average_loser_r: number;
  sample_size_warning: string | null;
}

export interface JournalReview {
  period_start: string | null;
  period_end: string | null;
  overall: GroupStats;
  by_strategy: GroupStats[];
  by_regime: GroupStats[];
  patterns: string[];
  repeated_mistakes: string[];
  rule_violations: string[];
  lessons: string[];
  confidence: number;
  generated_at: string;
}

export interface PortfolioSummaryOut {
  open_trade_count: number;
  open_exposure_value: number;
  trades_by_status: Record<string, number>;
}

// --- Phase 28: intelligence surfaces ----------------------------------------
// Field optionality mirrors the API exactly. Where the API can return null,
// the type says `| null` -- widening these to plain `number` would let a
// missing value silently render as 0 and undo the backend's care.

export type EvidenceOut = {
  kind: string;
  detail: string;
  stance: string;
  value?: number | string | null;
};

export type SignalOut = {
  id: number;
  asset_id: number;
  ticker: string;
  category: string;
  confidence: number | null;
  reasoning: string | null;
  evidence: EvidenceOut[];
  status: string;
  generated_at: string;
  acknowledged_at: string | null;
  market_regime: string | null;
  thesis_assessment: string | null;
  latest_research_at: string | null;
};

export type PositionOut = {
  ticker: string;
  quantity: number;
  average_cost: number;
  current_price: number | null;
  market_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
  allocation: number;
  unpriced: boolean;
};

export type PortfolioOut = {
  portfolio_name: string;
  base_currency: string;
  cash: number;
  positions_value: number;
  total_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
  total_return: number;
  exposure: number;
  position_count: number;
  unpriced_positions: number;
};

export type PortfolioPerformanceOut = {
  portfolio_name: string;
  snapshots: number;
  total_return: number;
  daily_return: number | null;
  cagr: number;
  sharpe: number;
  volatility: number;
  max_drawdown: number;
  current_equity: number;
  current_exposure: number;
  fully_priced: boolean;
  caveat: string | null;
};

export type ExposureBucketOut = { label: string; value: number; weight: number };

export type ExposureOut = {
  portfolio_name: string;
  gross_exposure: number;
  cash_weight: number;
  by_sector: ExposureBucketOut[];
  by_asset: ExposureBucketOut[];
  unpriced_positions: number;
};

export type ResearchQueueOut = {
  id: number;
  asset_id: number;
  ticker: string;
  change_type: string;
  status: string;
  score: number;
  importance: number;
  novelty: number;
  portfolio_impact: number;
  watchlist_relevance: number;
  reasons: string[];
  detail: Record<string, unknown>;
  detected_at: string;
  processed_at: string | null;
  research_document_id: number | null;
  note: string | null;
};

export type PaperTradeOut = {
  id: number;
  ticker: string;
  direction: string;
  quantity: number;
  entry_price: number;
  exit_price: number | null;
  stop_price: number | null;
  status: string;
  opened_at: string;
  closed_at: string | null;
  realized_pnl: number | null;
  r_multiple: number | null;
  signal_id: number | null;
  rationale: string | null;
};

export type PaperTradePerformanceOut = {
  trade_count: number;
  scored_trades: number;
  win_rate: number;
  profit_factor: number;
  expectancy_r: number;
  average_winner_r: number;
  average_loser_r: number;
  max_drawdown: number;
  is_significant: boolean;
  caveat: string | null;
};

export type BacktestOut = {
  id: number;
  strategy: string;
  ticker: string;
  start_date: string;
  end_date: string;
  initial_capital: number;
  parameters: Record<string, unknown>;
  total_return: number | null;
  cagr: number | null;
  sharpe: number | null;
  max_drawdown: number | null;
  win_rate: number | null;
  trade_count: number;
  created_at: string;
};

export type LearningSummaryOut =
  | { available: false; reason: string }
  | {
      available: true;
      period_start: string;
      period_end: string;
      generated_at: string;
      signal_accuracy: number | null;
      signal_sample_size: number | null;
      signal_is_significant: boolean | null;
      signal_caveat: string | null;
      theses_tracked: number | null;
      invalidation_rate: number | null;
      median_days_to_invalidation: number | null;
      research_is_accuracy_score: boolean;
      research_note: string | null;
    };

export type LearningReportOut = {
  id: number;
  kind: string;
  period_start: string;
  period_end: string;
  generated_at: string;
  obsidian_note_path: string | null;
  metrics: Record<string, unknown>;
};

export type HealthCheck = {
  name: string;
  status: HealthStatus;
  detail: string;
  data?: Record<string, unknown>;
};

export type HealthStatus = "healthy" | "degraded" | "unavailable";

export type HealthOut = {
  status: HealthStatus;
  checks: HealthCheck[];
  generated_at?: string;
};

export type LineageNode = {
  stage: string;
  recorded: boolean;
  summary: string;
  reference?: string | null;
};

export type SignalLineageOut = {
  signal_id: number;
  chain: LineageNode[];
  evidence: EvidenceOut[];
};
