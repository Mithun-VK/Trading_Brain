"""SQLAlchemy ORM models. Import every model module here so `Base.metadata`
is fully populated for Alembic autogenerate and `Base.metadata.create_all`.
"""

from models.ai_request import AIRequestRecord
from models.asset import Asset
from models.backtest_run import BacktestRun
from models.base import Base
from models.company import Company
from models.data_validation_error import DataValidationError
from models.financial_metric import FinancialMetric
from models.job_run import JobRun
from models.learning_review import LearningReview
from models.market_event import MarketEvent
from models.market_regime import MarketRegimeObservation
from models.paper_portfolio import PaperPortfolio, PaperPosition, PaperTransaction
from models.paper_portfolio_snapshot import PaperPortfolioSnapshot
from models.paper_trade_proposal import PaperTradeProposal
from models.position import Position
from models.price import Price
from models.research_document import ResearchDocument
from models.research_queue import ResearchQueueEntry
from models.signal import Signal
from models.strategy import Strategy
from models.thesis import Thesis
from models.thesis_review_record import ThesisReviewRecord
from models.trade import Trade
from models.watchlist import Watchlist, WatchlistItem

__all__ = [
    "Base",
    "Asset",
    "BacktestRun",
    "Company",
    "DataValidationError",
    "FinancialMetric",
    "AIRequestRecord",
    "JobRun",
    "LearningReview",
    "MarketEvent",
    "MarketRegimeObservation",
    "PaperPortfolio",
    "PaperPosition",
    "PaperTransaction",
    "PaperPortfolioSnapshot",
    "PaperTradeProposal",
    "Position",
    "Price",
    "ResearchDocument",
    "ResearchQueueEntry",
    "Signal",
    "Strategy",
    "Thesis",
    "ThesisReviewRecord",
    "Trade",
    "Watchlist",
    "WatchlistItem",
]
