"""2. 참조 관계. ForeignKey 는 스키마 없이 테이블 이름만 쓴다."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import EntityBase, table_options


class Quote(EntityBase):
    """종목별 일별 종가."""

    __tablename__ = "quote"
    __table_args__ = (
        UniqueConstraint("instrument_id", "quote_date", name="uq_quote_natural_key"),
        Index("ix_quote_instrument_id", "instrument_id"),
        table_options(comment="종목별 일별 종가"),
    )

    instrument_id: Mapped[UUID] = mapped_column(
        ForeignKey("instrument.id", ondelete="RESTRICT"),
        nullable=False,
        comment="참조하는 instrument 레코드 ID",
    )
    quote_date: Mapped[date] = mapped_column(nullable=False, comment="시세 기준일")
    close: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, comment="종가")
