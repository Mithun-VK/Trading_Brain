"""Paper trading: simulated orders, tracking, and journal integration.

Two guarantees hold throughout this package:
- a proposal executes only after **explicit human approval** (Rule 7)
- execution touches this database and nothing else -- there is no broker
  connectivity anywhere in TradingBrain (Rule 8)
"""

from paper_trading.journal import (
    close_trade_record,
    journal_paper_fill,
    open_trade_record,
)
from paper_trading.proposals import (
    ApprovalRequiredError,
    ProposalError,
    approve,
    execute_proposal,
    expire,
    list_proposals,
    propose_from_signal,
    reject,
)
from paper_trading.tracking import (
    PerformanceSummary,
    get_snapshots,
    latest_prices,
    performance,
    take_snapshot,
)

__all__ = [
    "propose_from_signal",
    "approve",
    "reject",
    "expire",
    "execute_proposal",
    "list_proposals",
    "ProposalError",
    "ApprovalRequiredError",
    "take_snapshot",
    "get_snapshots",
    "performance",
    "latest_prices",
    "PerformanceSummary",
    "open_trade_record",
    "close_trade_record",
    "journal_paper_fill",
]
