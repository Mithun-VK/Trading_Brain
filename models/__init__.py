"""SQLAlchemy ORM models. Import every model module here so `Base.metadata`
is fully populated for Alembic autogenerate and `Base.metadata.create_all`.
"""

from models.asset import Asset
from models.base import Base
from models.company import Company
from models.data_validation_error import DataValidationError
from models.financial_metric import FinancialMetric
from models.job_run import JobRun
from models.market_event import MarketEvent
from models.market_regime import MarketRegimeObservation
from models.paper_portfolio import PaperPortfolio, PaperPosition, PaperTransaction
from models.position import Position
from models.price import Price
from models.research_document import ResearchDocument
from models.research_queue import ResearchQueueEntry
from models.signal import Signal
from models.strategy import Strategy
from models.thesis import Thesis
from models.trade import Trade
from models.watchlist import Watchlist, WatchlistItem

__all__ = [
    "Base",
    "Asset",
    "Company",
    "DataValidationError",
    "FinancialMetric",
    "JobRun",
    "MarketEvent",
    "MarketRegimeObservation",
    "PaperPortfolio",
    "PaperPosition",
    "PaperTransaction",
    "Position",
    "Price",
    "ResearchDocument",
    "ResearchQueueEntry",
    "Signal",
    "Strategy",
    "Thesis",
    "Trade",
    "Watchlist",
    "WatchlistItem",
]
