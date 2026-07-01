import asyncio

from fastapi.responses import Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from backend.logger import logger
from backend.schema._input import NodeCreate
from .requests import NodeRequests
from backend.db import crud
from backend.db.models import Node


async def add_node_handler(request: NodeCreate, db: Session) -> bool:
    new_node = NodeRequests(
        request.address,
        request.port,
        request.key,
        request.tunnel_address,
        request.protocol,
        request.ovpn_port,
        request.set_new_setting,
    )
    # check_node() does blocking HTTP; keep it off the event loop.
    if await run_in_threadpool(new_node.check_node):
        crud.create_node(db, request)
        logger.info(f"Node added successfully: {request.address}:{request.port}")
        return True
    else:
        logger.warning(f"Failed to add node: {request.address}:{request.port}")
        return False


async def update_node_handler(node_id: int, request: NodeCreate, db: Session) -> bool:
    """Update a node + force full config + multi-login sync"""
    crud.update_node(db, node_id, request)

    node_req = NodeRequests(
        address=request.address,
        port=request.port,
        api_key=request.key,
        tunnel_address=request.tunnel_address,
        protocol=request.protocol,
        ovpn_port=request.ovpn_port,
        set_new_setting=True,
    )

    # 1. Apply new server settings + multi-login scripts
    await run_in_threadpool(node_req.check_node)

    # 2. Push every user's max_logins + re-create users on the node.
    # This is critical so multi-login works after port/protocol change.
    try:
        from backend.db import crud as db_crud
        users = db_crud.get_all_users(db)
        for u in users:
            max_l = getattr(u, 'max_logins', 1) or 1
            cn = f"{u.name}-{request.name}"
            await run_in_threadpool(node_req.set_user_limit, cn, max_l)
            await run_in_threadpool(node_req.create_user, cn, max_l)
    except Exception as e:
        logger.warning(f"Could not push max_logins after node edit: {e}")

    logger.info(f"Node updated + multi-login limits pushed: {request.address}:{request.port}")
    return True


async def delete_node_handler(node_id: int, db: Session) -> bool:
    """Delete a node"""
    node = crud.get_node_by_id(db, node_id)
    if node:
        crud.delete_node(db, node.id)
        logger.info(f"Node deleted successfully: {node.name}")
        return True
    else:
        logger.warning(f"Failed to delete node: {node.name}")
        return False


async def list_nodes_handler(db: Session) -> list:
    """Retrieve all nodes"""
    nodes_list = []
    nodes = crud.get_all_nodes(db)
    for node in nodes:
        node_info = {
            "id": node.id,
            "name": node.name,
            "address": node.address,
            "tunnel-address": node.tunnel_address,
            "tunnel_address": node.tunnel_address,
            "ovpn_port": node.ovpn_port,
            "protocol": node.protocol,
            "port": node.port,
            "key": node.key,
            "status": "active" if node.status else "inactive",
        }
        nodes_list.append(node_info)
    return nodes_list


async def get_node_status_handler(node_id: int, db: Session):
    """Get the status of a node"""
    node = crud.get_node_by_id(db, node_id)
    if node:
        # get_node_info() uses blocking `requests`; run it in a threadpool so a
        # slow/unreachable node can't block the event loop (which would freeze
        # the whole panel and make the dashboard hang / show 0 active nodes).
        node_status = await run_in_threadpool(
            NodeRequests(
                address=node.address, port=node.port, api_key=node.key
            ).get_node_info
        )
        return {
            "address": node.address,
            "port": node.port,
            "status": "active" if node.status else "inactive",
            "node_info": node_status,
        }
    return None


async def create_user_on_all_nodes(name: str, db: Session, max_logins: int = 1):
    """Create a user on all nodes (concurrently, off the event loop)."""
    nodes = crud.get_all_nodes(db)
    if not nodes:
        return

    def work(node):
        req = NodeRequests(address=node.address, port=node.port, api_key=node.key)
        if req.check_node():
            req.create_user(f"{name}-{node.name}", max_logins=max_logins)
            logger.info(
                f"User '{name}-{node.name}' created on node {node.address}:{node.port}"
            )
        else:
            logger.warning(
                f"Failed to create user '{name}-{node.name}' on node {node.address}:{node.port}"
            )

    await asyncio.gather(
        *[run_in_threadpool(work, node) for node in nodes], return_exceptions=True
    )


async def change_user_status_on_all_nodes(
    uuid: str, name: str, status: bool, db: Session
):
    nodes = crud.get_all_nodes(db)
    crud.change_user_status(db, uuid, status)

    user = crud.get_user_by_uuid(db, uuid)
    max_logins = user.max_logins if user else 1

    if not nodes:
        return

    def work(node):
        req = NodeRequests(address=node.address, port=node.port, api_key=node.key)
        if req.check_node():
            req.change_user_status(
                f"{name}-{node.name}", status, max_logins=max_logins
            )
            logger.info(
                f"User '{name}-{node.name}' changed status on node {node.address}:{node.port}"
            )
        else:
            logger.warning(
                f"Failed to change user status '{name}-{node.name}' on node {node.address}:{node.port}"
            )

    await asyncio.gather(
        *[run_in_threadpool(work, node) for node in nodes], return_exceptions=True
    )


async def set_user_limit_on_all_nodes(name: str, max_logins: int, db: Session):
    """Push the max simultaneous logins limit for a user to all nodes."""
    nodes = crud.get_all_nodes(db)
    if not nodes:
        return

    def work(node):
        req = NodeRequests(address=node.address, port=node.port, api_key=node.key)
        if req.check_node():
            req.set_user_limit(f"{name}-{node.name}", max_logins)
            logger.info(
                f"User '{name}-{node.name}' login limit set to {max_logins} "
                f"on node {node.address}:{node.port}"
            )
        else:
            logger.warning(
                f"Failed to set login limit for '{name}-{node.name}' "
                f"on node {node.address}:{node.port}"
            )

    await asyncio.gather(
        *[run_in_threadpool(work, node) for node in nodes], return_exceptions=True
    )


async def download_ovpn_client_from_node(
    uuid: str, node_id: int, db: Session
) -> Response | None:
    """Download OVPN client from a node"""
    node = crud.get_node_by_id(db, node_id)
    user = crud.get_user_by_uuid(db, uuid)
    if not node or not user:
        return None
    node_request = NodeRequests(
        address=node.address, port=node.port, api_key=node.key
    )
    # Blocking HTTP -> threadpool.
    result = await run_in_threadpool(
        node_request.download_ovpn_client, f"{user.name}-{node.name}"
    )
    if result:
        # Ensure the node knows this user's simultaneous-login limit.
        await run_in_threadpool(
            node_request.set_user_limit, f"{user.name}-{node.name}", user.max_logins
        )
        logger.info(
            f"OVPN client downloaded for user '{user.name}-{node.name}' on node {node.address}:{node.port}"
        )
        return result
    return None


async def delete_user_on_all_nodes(name: str, db: Session) -> bool:
    """Delete a user from all nodes (concurrently, off the event loop)."""
    nodes = crud.get_all_nodes(db)
    if not nodes:
        return False

    def work(node):
        req = NodeRequests(address=node.address, port=node.port, api_key=node.key)
        if req.check_node():
            req.delete_user(f"{name}-{node.name}")
            logger.info(
                f"User '{name}-{node.name}' deleted on node {node.address}:{node.port}"
            )
        else:
            logger.warning(
                f"Failed to delete user '{name}-{node.name}' on node {node.address}:{node.port}"
            )

    await asyncio.gather(
        *[run_in_threadpool(work, node) for node in nodes], return_exceptions=True
    )
    return True


async def get_users_used_traffic(node: Node, db: Session) -> dict:
    """Get a node's usage: {"users": {cn: total}, "sessions": {cn: {key: bytes}}}.

    get_users_usage() uses blocking requests, so run it in a threadpool to keep
    the event loop free.
    """
    node_requests = NodeRequests(address=node.address, port=node.port, api_key=node.key)
    response = await run_in_threadpool(node_requests.get_users_usage)

    if not response:
        return {}
    return response
