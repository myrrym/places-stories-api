"""Database schema.

Two tables. ``places`` is the geospatial backbone (the *where*),
``stories`` is the narrative layer (the *why it matters*). Every story row
carries its own provenance -- source, URL, licence, when it was fetched,
and how confidently it was matched to the place. Attribution is a column,
not a footnote.
"""

from __future__ import annotations

import enum
from datetime import date, datetime

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Category(enum.StrEnum):
    historic = "historic"
    religious = "religious"
    museum = "museum"
    natural = "natural"
    market = "market"
    landmark = "landmark"


class MatchMethod(enum.StrEnum):
    """How a story was linked to its place. Drives the confidence story."""

    wikidata = "wikidata"  # OSM/Wikidata carried an explicit sitelink. Exact.
    geosearch = "geosearch"  # Wikipedia geosearch + fuzzy name match.
    manual = "manual"  # A human wrote or verified it in a pull request.


class Place(Base):
    __tablename__ = "places"

    # Slug primary key: readable URLs, and contributors can author a YAML
    # file without inventing a UUID. Also the natural upsert key.
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_local: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[Category] = mapped_column(
        Enum(Category, name="place_category", native_enum=True), nullable=False
    )
    geom: Mapped[object] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )
    address: Mapped[str | None] = mapped_column(String(300))
    city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(120))

    # Provenance of the base (coordinate) layer.
    osm_type: Mapped[str | None] = mapped_column(String(16))
    osm_id: Mapped[int | None] = mapped_column(BigInteger)
    wikidata_id: Mapped[str | None] = mapped_column(String(32))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    stories: Mapped[list[Story]] = relationship(
        back_populates="place",
        cascade="all, delete-orphan",
        order_by="Story.position",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_places_geom", "geom", postgresql_using="gist"),
        Index("ix_places_category", "category"),
        Index("ix_places_state", "state"),
    )


class Story(Base):
    __tablename__ = "stories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    place_id: Mapped[str] = mapped_column(
        ForeignKey("places.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str] = mapped_column(String(8), nullable=False, default="en")

    # Mandatory attribution.
    source_name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_url: Mapped[str] = mapped_column(String(600), nullable=False)
    license: Mapped[str] = mapped_column(String(80), nullable=False)
    retrieved_at: Mapped[date | None] = mapped_column(Date)

    match_method: Mapped[MatchMethod] = mapped_column(
        Enum(MatchMethod, name="story_match_method", native_enum=True), nullable=False
    )
    match_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    place: Mapped[Place] = relationship(back_populates="stories")

    __table_args__ = (
        CheckConstraint(
            "match_confidence >= 0 AND match_confidence <= 1", name="ck_stories_confidence_range"
        ),
    )
