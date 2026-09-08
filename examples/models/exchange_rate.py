"""3. 외부 시스템이 소유한 테이블. 읽고 쓸 수는 있지만 autogenerate 에 나오지 않는다."""

from decimal import Decimal

from sqlalchemy import Integer, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, table_options


class ExchangeRate(Base):
    """다른 서비스가 만들고 관리하는 환율 테이블.

    스키마를 이 프로젝트가 만들지 않으므로 `EntityBase` 가 아니라 `Base` 를 상속하고
    실제 컬럼 구조를 그대로 적는다.
    """

    __tablename__ = "exchange_rate"
    __table_args__ = (table_options(comment="외부에서 관리하는 환율 테이블", managed=False),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="외부 시스템의 기본키")
    base_currency: Mapped[str] = mapped_column(Text, nullable=False, comment="기준 통화")
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, comment="환율")
