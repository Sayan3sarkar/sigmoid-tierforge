from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base


class Store(Base):
    """One row of an uploaded store CSV. Input data: written once, never changed."""

    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    upload_id: Mapped[UUID] = mapped_column(Uuid)
    store_id: Mapped[str] = mapped_column(Text)
    store_name: Mapped[str] = mapped_column(Text)
    address: Mapped[str] = mapped_column(Text)
    city: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)
    country: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # Also serves "all stores of an upload" lookups (upload_id leads the index).
        UniqueConstraint("upload_id", "store_id"),
    )
