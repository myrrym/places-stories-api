"""Initial schema: PostGIS extension, places, stories.

Revision ID: 0001_initial
Revises:
"""

import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

CATEGORY_VALUES = ("historic", "religious", "museum", "natural", "market", "landmark")
MATCH_METHOD_VALUES = ("wikidata", "geosearch", "manual")

# Created explicitly below. The column definitions reference the types with
# create_type=False so create_table does not try to create them a second time.
category = sa.Enum(*CATEGORY_VALUES, name="place_category")
match_method = sa.Enum(*MATCH_METHOD_VALUES, name="story_match_method")

category_col = postgresql.ENUM(*CATEGORY_VALUES, name="place_category", create_type=False)
match_method_col = postgresql.ENUM(
    *MATCH_METHOD_VALUES, name="story_match_method", create_type=False
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    bind = op.get_bind()
    category.create(bind, checkfirst=True)
    match_method.create(bind, checkfirst=True)

    op.create_table(
        "places",
        sa.Column("id", sa.String(120), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_local", sa.String(200)),
        sa.Column("category", category_col, nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.Geography(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("address", sa.String(300)),
        sa.Column("city", sa.String(120)),
        sa.Column("state", sa.String(120)),
        sa.Column("osm_type", sa.String(16)),
        sa.Column("osm_id", sa.BigInteger),
        sa.Column("wikidata_id", sa.String(32)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    # The index that makes ST_DWithin index-assisted instead of a seq scan.
    op.create_index("ix_places_geom", "places", ["geom"], postgresql_using="gist")
    op.create_index("ix_places_category", "places", ["category"])
    op.create_index("ix_places_state", "places", ["state"])

    op.create_table(
        "stories",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "place_id",
            sa.String(120),
            sa.ForeignKey("places.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body_md", sa.Text, nullable=False),
        sa.Column("lang", sa.String(8), nullable=False, server_default="en"),
        sa.Column("source_name", sa.String(120), nullable=False),
        sa.Column("source_url", sa.String(600), nullable=False),
        sa.Column("license", sa.String(80), nullable=False),
        sa.Column("retrieved_at", sa.Date),
        sa.Column("match_method", match_method_col, nullable=False),
        sa.Column("match_confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.CheckConstraint(
            "match_confidence >= 0 AND match_confidence <= 1",
            name="ck_stories_confidence_range",
        ),
    )
    op.create_index("ix_stories_place_id", "stories", ["place_id"])


def downgrade() -> None:
    op.drop_table("stories")
    op.drop_table("places")
    bind = op.get_bind()
    match_method.drop(bind, checkfirst=True)
    category.drop(bind, checkfirst=True)
