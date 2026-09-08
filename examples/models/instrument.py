"""1. 기본. 이 프로젝트가 스키마를 소유하는 테이블."""

from enum import StrEnum

from sqlalchemy import CheckConstraint, Text, UniqueConstraint
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from core.database import EntityBase, table_options


class Market(StrEnum):
    KOSPI = "kospi"
    NASDAQ = "nasdaq"


class Instrument(EntityBase):
    """추적 종목 마스터."""

    __tablename__ = "instrument"
    __table_args__ = (
        UniqueConstraint("ticker", "market", name="uq_instrument_ticker_market"),
        # 값의 종류가 정해진 컬럼은 StrEnum + SQLAlchemy Enum + CHECK 제약을 함께 쓴다.
        # native_enum=False 로 두면 VARCHAR 로 저장되어 값 추가·삭제가 마이그레이션 없이 끝난다.
        CheckConstraint("market IN ('kospi', 'nasdaq')", name="ck_instrument_market"),
        table_options(comment="시세와 뉴스가 참조하는 추적 종목 마스터"),
    )

    ticker: Mapped[str] = mapped_column(
        Text, nullable=False, comment="거래 시장에서 사용하는 종목 코드"
    )
    market: Mapped[Market] = mapped_column(
        SqlEnum(
            Market,
            native_enum=False,
            length=20,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
        comment="종목이 상장된 거래 시장(kospi 또는 nasdaq)",
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, comment="종목 표시 이름")
