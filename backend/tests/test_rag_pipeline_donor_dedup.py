"""Regression tests for the text-chunk donor-clone dedup path (#2542).

A source PDF may have been indexed in several prior courses, each keeping its own
``document_chunks`` rows. ``_find_donor_chunks`` must clone from exactly ONE donor
resource — matching donors across all resources that share the ``content_hash`` and
cloning the union multiplies the new collection by the number of prior courses
(a file indexed in 2 courses previously produced 2× the chunks: e.g. 3316 instead
of 1658). These are mock-session unit tests so they run without a live DB (the
DB-backed conftest can't materialize the PG enums — see project notes).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.rag.pipeline import RAGPipeline


def _chunk(resource_id, chunk_index, content=None, page=1):
    c = MagicMock()
    c.course_resource_id = resource_id
    c.chunk_index = chunk_index
    c.content = content if content is not None else f"chunk-{chunk_index}"
    c.page = page
    c.embedding = [0.0]
    c.chapter = None
    c.level = None
    c.language = "en"
    c.token_count = 10
    return c


class TestFindDonorChunksSingleDonor:
    def setup_method(self):
        self.pipeline = RAGPipeline(AsyncMock())

    @pytest.mark.asyncio
    async def test_clones_from_a_single_donor_not_the_union(self):
        """With two prior resources sharing the content_hash, only one donor's
        chunks are returned — never the concatenation of both."""
        donor_a = uuid.uuid4()
        new_resource = uuid.uuid4()
        donor_a_chunks = [_chunk(donor_a, i) for i in range(1658)]

        # First execute() picks one donor resource id; second returns that
        # resource's chunks. The buggy version issued a single union query.
        donor_id_result = MagicMock()
        donor_id_result.scalar_one_or_none = MagicMock(return_value=donor_a)
        chunks_result = MagicMock()
        chunks_result.scalars.return_value.all.return_value = donor_a_chunks

        session = MagicMock()
        session.execute = AsyncMock(side_effect=[donor_id_result, chunks_result])

        donors = await self.pipeline._find_donor_chunks("hash-x", new_resource, session)

        # Exactly one donor's worth — not 2× — and all from the same resource.
        assert len(donors) == 1658
        assert {d.course_resource_id for d in donors} == {donor_a}
        # Two-step lookup: pick-one-donor then fetch-its-chunks (regression guard
        # against reverting to the single union SELECT that over-clones).
        assert session.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_clone_dedups_a_dirty_donor(self):
        """A donor collection may itself hold duplicate rows (duplication compounded
        across course generations). Cloning must collapse them to one copy per
        logical chunk so the new collection lands on the clean count, not the
        donor's inflated count."""
        donor = uuid.uuid4()
        new_resource = uuid.uuid4()
        # 3 unique logical chunks, each present twice in the donor (6 rows).
        dirty = []
        for i in range(3):
            dirty.append(_chunk(donor, i, content=f"body-{i}", page=1))
            dirty.append(_chunk(donor, i, content=f"body-{i}", page=1))

        session = MagicMock()
        session.add = MagicMock()
        session.commit = AsyncMock()

        cloned = await self.pipeline._clone_chunks(dirty, "new-src", new_resource, session)

        assert cloned == 3
        assert session.add.call_count == 3

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_donor_resource(self):
        no_donor = MagicMock()
        no_donor.scalar_one_or_none = MagicMock(return_value=None)
        session = MagicMock()
        session.execute = AsyncMock(return_value=no_donor)

        donors = await self.pipeline._find_donor_chunks("hash-x", uuid.uuid4(), session)

        assert donors == []
        # Short-circuits after the donor-id lookup — never fetches chunks.
        assert session.execute.await_count == 1
