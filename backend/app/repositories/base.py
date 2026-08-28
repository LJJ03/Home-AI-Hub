"""Generic asynchronous repository primitives."""

from collections.abc import Mapping, Sequence
from typing import Generic, TypeVar

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base


ModelT = TypeVar("ModelT", bound=Base)
IdentifierT = TypeVar("IdentifierT")


class BaseRepository(Generic[ModelT, IdentifierT]):
    """Provide transaction-neutral CRUD operations for one ORM model."""

    def __init__(self, model: type[ModelT], session: AsyncSession) -> None:
        mapper = inspect(model)
        primary_key_fields = {
            mapper.get_property_by_column(column).key for column in mapper.primary_key
        }

        self._model = model
        self._session = session
        self._primary_key_columns = tuple(mapper.primary_key)
        self._updatable_fields = frozenset(
            attribute.key
            for attribute in mapper.column_attrs
            if attribute.key not in primary_key_fields
        )

    async def create(self, entity: ModelT) -> ModelT:
        """Add an entity and load its database-generated values."""

        if not isinstance(entity, self._model):
            raise TypeError(f"Expected an instance of {self._model.__name__}")

        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def get(self, identifier: IdentifierT) -> ModelT | None:
        """Return one entity by primary key."""

        return await self._session.get(self._model, identifier)

    async def list(self, *, offset: int = 0, limit: int = 100) -> Sequence[ModelT]:
        """Return a deterministic primary-key ordered page of entities."""

        if offset < 0:
            raise ValueError("offset must be greater than or equal to zero")
        if limit <= 0:
            raise ValueError("limit must be greater than zero")

        statement = (
            select(self._model)
            .order_by(*self._primary_key_columns)
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.scalars(statement)
        return result.all()

    async def update(
        self,
        identifier: IdentifierT,
        values: Mapping[str, object],
    ) -> ModelT | None:
        """Update mapped non-primary-key columns on an existing entity."""

        invalid_fields = set(values).difference(self._updatable_fields)
        if invalid_fields:
            fields = ", ".join(sorted(invalid_fields))
            raise ValueError(f"Fields are not updatable: {fields}")

        entity = await self.get(identifier)
        if entity is None:
            return None

        for field, value in values.items():
            setattr(entity, field, value)

        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def delete(self, identifier: IdentifierT) -> bool:
        """Delete an entity by primary key and report whether it existed."""

        entity = await self.get(identifier)
        if entity is None:
            return False

        await self._session.delete(entity)
        await self._session.flush()
        return True

