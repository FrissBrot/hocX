"""public_id: adds the shared uuidv7() SQL function used as server_default for every
new public_id column introduced in the following migrations (0066-0068).

PostgreSQL 16 has no native UUIDv7 generator (that lands in PG 18). This function builds
one from a 48-bit big-endian millisecond Unix timestamp prefix + 74 random bits from
pgcrypto's gen_random_bytes(), with the version (0111) and variant (10) bits forced per
RFC 9562 sec 5.7. Chosen over the pg_uuidv7 C extension so the project doesn't need a
custom postgres:16 image - pgcrypto ships in the stock image, just needs enabling.

Verified against a live PG 16 instance before this migration was written: version nibble
is always '7', variant nibble is always in [8,9,a,b], 100k generated values had zero
collisions, and values generated in separate time-separated batches sort in generation
order (the property callers rely on for "created_at-equivalent" ordering by public_id).

Deliberately centralized here (not duplicated app-side in Python/SQLAlchemy) because not
every insert into a public_id-bearing table goes through the main backend's ORM layer -
see abgabebox-backend/app/models.py, which does raw Core inserts against these tables
under a restricted Postgres role and must get a valid public_id purely from the column's
server_default.

Revision ID: 0065_public_id_function
Revises: 0064_entry_exit_block
Create Date: 2026-08-25
"""

from alembic import op

revision = "0065_public_id_function"
down_revision = "0064_entry_exit_block"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION uuidv7() RETURNS uuid
        LANGUAGE plpgsql VOLATILE PARALLEL SAFE
        AS $$
        DECLARE
            unix_ts_ms bytea;
            rand_bytes bytea;
            result bytea;
        BEGIN
            unix_ts_ms := substring(int8send(floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint) FROM 3 FOR 6);
            rand_bytes := gen_random_bytes(10);

            result := unix_ts_ms || rand_bytes;

            -- byte 6: high nibble forced to 0111 (version 7), low nibble stays random
            result := set_byte(result, 6, (b'0111' || substring(get_byte(result, 6)::bit(8) FROM 5 FOR 4))::bit(8)::int);
            -- byte 8: top two bits forced to 10 (RFC 9562 variant), remaining 6 bits stay random
            result := set_byte(result, 8, (b'10' || substring(get_byte(result, 8)::bit(8) FROM 3 FOR 6))::bit(8)::int);

            RETURN encode(result, 'hex')::uuid;
        END;
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS uuidv7()")
