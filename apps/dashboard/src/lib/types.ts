// Mirrors apps/api/schemas.py and the brain/*/schemas.py Pydantic models.
// Keep these in sync by hand -- there is no shared codegen in this phase.

export interface HealthOut {
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
