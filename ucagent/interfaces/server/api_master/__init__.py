"""Master API server and heartbeat client for UCAgent."""

from ucagent.interfaces.server.api_master.client import MasterClient
from ucagent.interfaces.server.api_master.server import MasterApiServer

__all__ = ["MasterApiServer", "MasterClient"]
