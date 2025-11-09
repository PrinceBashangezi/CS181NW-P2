from typing import Any, Optional


class PacketManager:
    """
    Tracks packet-related state for a DV server instance.
    Intended to be used by dv.Server (one PacketManager per Server).
    """
    def __init__(self) -> None:
        self._packets_received_since_last: int = 0
        self._packet_logging_enabled: bool = False

    def enable_logging(self) -> None:
        self._packet_logging_enabled = True

    def disable_logging(self) -> None:
        self._packet_logging_enabled = False

    def is_logging_enabled(self) -> bool:
        return self._packet_logging_enabled

    def record_packet(self, packet: Optional[bytes] = None, src_addr: Optional[tuple] = None) -> None:
        """
        Record that a routing packet was received. Optionally log it if enabled.
        """
        self._packets_received_since_last += 1
        if self._packet_logging_enabled and src_addr is not None:
            try:
                print(f"Packet received from {src_addr[0]}:{src_addr[1]}")
            except Exception:
                # Avoid crashing due to unexpected print failures
                pass

    def get_and_reset_count(self) -> int:
        """
        Return the number of packets received since the last call and reset the counter.
        """
        count = self._packets_received_since_last
        self._packets_received_since_last = 0
        return count


def handle_packets_command(server: Any, *args: str) -> str:
    """
    Implements: packets [on|off]
      - 'packets' with no args: prints number of routing packets received since last query
      - 'packets on/off': toggle verbose logging of received packets
    """
    if not hasattr(server, "packet_manager") or server.packet_manager is None:
        return "packets SERVER NOT INITIALIZED"

    # toggle mode if provided
    if len(args) == 1:
        mode = args[0].strip().lower()
        if mode == "on":
            server.packet_manager.enable_logging()
            return "packets on SUCCESS"
        if mode == "off":
            server.packet_manager.disable_logging()
            return "packets off SUCCESS"
        return "packets INVALID ARG"

    # default behavior: show count since last call
    count = server.packet_manager.get_and_reset_count()
    return f"packets SUCCESS {count}"


def handle_crash_command(server: Any) -> str:
    """
    Implements: crash
    Closes the server socket and marks the server as crashed.
    """
    try:
        # Mark crashed (if such a flag exists later)
        setattr(server, "crashed", True)
        # Stop/close underlying socket
        if hasattr(server, "stop"):
            server.stop()
        return "crash SUCCESS"
    except Exception as e:
        return f"crash ERROR {e}"


