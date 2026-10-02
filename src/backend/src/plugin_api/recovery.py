"""Recover interrupted host/runtime transactions using database commit receipts."""

import logging
import time
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.plugin_permissions import PluginLifecycleTransaction, PluginPermissionGrant
from .manager_state import manager_state
from .lifecycle_lock import serialized_lifecycle
from .runtime_client import PluginRuntimeClient, PluginRuntimeRequestError, PluginRuntimeUnavailable


@serialized_lifecycle
async def recover_transactions(runtime: PluginRuntimeClient, db: AsyncSession) -> None:
    """Recover abandoned transactions while excluding new installations."""
    for plugin in await runtime.plugins():
        pending = plugin.get("pending_transaction")
        if not pending:
            continue
        plugin_id = plugin["plugin_id"]
        operation = pending["operation_id"]
        receipt = await db.get(PluginLifecycleTransaction, UUID(operation))
        if receipt is None:
            # Absence of the atomic receipt proves grants never committed.
            if pending["phase"] == "prepared":
                await runtime.finish_installation(plugin_id, operation, commit=False)
            else:
                raise PluginRuntimeRequestError("Activation has no durable grant commit receipt")
            continue
        if pending["phase"] == "prepared":
            await runtime.finish_installation(plugin_id, operation, commit=True)
        previous = pending.get("previous_state")
        should_start = previous is None or (
            previous.get("enabled") and previous.get("status") != "stopped"
        )
        try:
            if should_start and plugin.get("status") != "running":
                await runtime.start(
                    plugin_id,
                    user_id=(previous or {}).get("user_id")
                    or (str(receipt.user_id) if receipt.user_id else None),
                )
            healthy = not should_start or await runtime.plugin_health(plugin_id)
        except (PluginRuntimeRequestError, PluginRuntimeUnavailable):
            healthy = False
        if not healthy and previous is not None:
            await runtime.stop(plugin_id)
            await db.execute(
                update(PluginPermissionGrant)
                .where(
                    PluginPermissionGrant.id.in_([UUID(value) for value in receipt.added_grants]),
                )
                .values(revoked_at=int(time.time()))
            )
            await db.execute(
                update(PluginPermissionGrant)
                .where(
                    PluginPermissionGrant.id.in_([UUID(value) for value in receipt.removed_grants]),
                    PluginPermissionGrant.revoked_by_operation == receipt.id,
                )
                .values(revoked_at=None, revoked_by_operation=None)
            )
            await db.commit()
            await runtime.finish_activation(plugin_id, operation, commit=False)
            manager_state().patch(
                plugin_id,
                last_update_error="Interrupted update failed health verification; previous release restored.",
            )
            logging.getLogger(__name__).warning("Recovered failed plugin update: %s", plugin_id)
        else:
            await runtime.finish_activation(plugin_id, operation, commit=True)
            await runtime.prune_history(
                plugin_id, int(manager_state().settings()["retained_versions"])
            )
        receipt.completed = True
        await db.commit()
    manager_state().reconcile(await runtime.plugins())
