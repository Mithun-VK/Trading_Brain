"""Idempotent persistence of company profiles and fundamental metrics."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from data.ingestion.schemas import CompanyProfile, FundamentalsSnapshot
from models.asset import Asset
from models.company import Company
from models.financial_metric import FinancialMetric

# Vendor snapshot metrics are trailing-twelve-month figures; recording the
# period explicitly keeps them distinguishable from period-specific filings
# loaded later.
SNAPSHOT_PERIOD = "TTM"


def upsert_company_profile(session: Session, asset: Asset, profile: CompanyProfile) -> Company:
    """Create or update the Company row for an asset.

    Fields the provider couldn't supply (None) are left untouched rather
    than overwriting a previously-known value with a blank.
    """
    company = session.scalars(select(Company).where(Company.asset_id == asset.id)).first()
    if company is None:
        company = Company(asset_id=asset.id)
        session.add(company)

    if profile.sector is not None:
        company.sector = profile.sector
    if profile.industry is not None:
        company.industry = profile.industry
    if profile.market_cap is not None:
        company.market_cap = profile.market_cap

    session.flush()
    return company


def upsert_fundamentals(
    session: Session, asset_id: int, snapshot: FundamentalsSnapshot
) -> tuple[int, int]:
    """Upsert every metric in a snapshot.

    Returns (inserted, updated). Keyed on the table's natural key
    (asset_id, metric_name, period, as_of_date), so re-running an update job
    on the same day refreshes values instead of duplicating them.
    """
    inserted = 0
    updated = 0

    for metric_name, value in snapshot.metrics.items():
        existing = session.scalars(
            select(FinancialMetric).where(
                FinancialMetric.asset_id == asset_id,
                FinancialMetric.metric_name == metric_name,
                FinancialMetric.period == SNAPSHOT_PERIOD,
                FinancialMetric.as_of_date == snapshot.as_of_date,
            )
        ).first()

        if existing is None:
            session.add(
                FinancialMetric(
                    asset_id=asset_id,
                    metric_name=metric_name,
                    period=SNAPSHOT_PERIOD,
                    value=value,
                    as_of_date=snapshot.as_of_date,
                    source=snapshot.source,
                )
            )
            inserted += 1
        else:
            existing.value = value
            existing.source = snapshot.source
            updated += 1

    session.flush()
    return inserted, updated


def get_latest_metrics(session: Session, asset_id: int) -> dict[str, float]:
    """Most recent value per metric name -- the shape the research context wants."""
    rows = session.scalars(
        select(FinancialMetric)
        .where(FinancialMetric.asset_id == asset_id)
        .order_by(FinancialMetric.as_of_date.asc())
    ).all()
    return {row.metric_name: float(row.value) for row in rows}
