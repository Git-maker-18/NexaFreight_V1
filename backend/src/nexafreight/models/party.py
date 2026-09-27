"""Demo-world parties (Task 18, P1): shippers, consignees, carriers.

Fictional-but-realistic Indian export-chain actors. Orders link to parties
via nullable FKs (shipper/consignee/carrier); the dripper assigns them
deterministically so every world rebuild tells the same India story.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexafreight.enums import PartyRole
from nexafreight.models.base import Base
from nexafreight.models.mixins import TimestampMixin


class Party(Base, TimestampMixin):
    """A named actor in the demo supply chain (shipper / consignee / carrier)."""

    __tablename__ = "parties"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    role: Mapped[PartyRole] = mapped_column(String(20), nullable=False)
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="IN")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    orders_as_shipper: Mapped[list["Order"]] = relationship(  # noqa: F821
        "Order", back_populates="shipper", foreign_keys="Order.shipper_id"
    )
    orders_as_consignee: Mapped[list["Order"]] = relationship(  # noqa: F821
        "Order", back_populates="consignee", foreign_keys="Order.consignee_id"
    )
    orders_as_carrier: Mapped[list["Order"]] = relationship(  # noqa: F821
        "Order", back_populates="carrier", foreign_keys="Order.carrier_id"
    )
