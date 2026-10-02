"""Private process-hosting primitives for APEX."""

from core.host.identity import HostContext, HostIdentity, HostingMode, create_host_context, create_host_identity
from core.host.profile_lock import ProfileAlreadyRunningError, ProfileLock
from core.host.processes import (
    OwnedProcessRegistry,
    register_owned_process,
    terminate_owned_processes,
    unregister_owned_process,
)
from core.host.protocol import (
    ControlChannel,
    ControlEnvelope,
    ControlProtocolError,
    decode_frame,
    encode_envelope,
    validate_envelope,
)

__all__ = [
    "HostContext",
    "HostIdentity",
    "HostingMode",
    "ProfileAlreadyRunningError",
    "ProfileLock",
    "OwnedProcessRegistry",
    "ControlChannel",
    "ControlEnvelope",
    "ControlProtocolError",
    "create_host_context",
    "create_host_identity",
    "decode_frame",
    "encode_envelope",
    "register_owned_process",
    "terminate_owned_processes",
    "unregister_owned_process",
    "validate_envelope",
]
