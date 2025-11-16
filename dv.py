"""
dv.py — Project 2 Distance Vector main program

This file ties together:
- prince.py:  Server, topology parsing, display, disable
- sultan.py:  Distance Vector logic (update, step, periodic sender, ingest DV)
- bryson.py:  Packet counting/logging and crash command

The TA should run this script and interact with it via the commands
described in the project handout, e.g.:

  server -t <topology-file> -i <routing-update-interval>
  display
  update <server-ID1> <server-ID2> <cost|inf>
  step
  packets [on|off]
  disable <server-ID>
  crash
  quit / exit
"""

import socket
import threading
from typing import Optional, Dict

from prince import Server
from sultan import (
    INF,
    parse_cost,
    handle_update_command,
    handle_step_command,
    start_periodic_updates,
    stop_periodic_updates,
    ingest_neighbor_vector,
)
from bryson import PacketManager, handle_packets_command, handle_crash_command


###############################################################################
# Helper functions for parsing user commands
###############################################################################

def parse_server_command(command_line: str):
    """
    Parse: server -t <topology-file> -i <interval>
    Returns (topology_file, interval) or (None, None) if invalid.
    """
    parts = command_line.strip().split()

    if len(parts) < 5 or parts[0] != "server":
        return None, None

    topology_file: Optional[str] = None
    interval: Optional[int] = None

    i = 1
    while i < len(parts):
        if parts[i] == "-t" and i + 1 < len(parts):
            topology_file = parts[i + 1]
            i += 2
        elif parts[i] == "-i" and i + 1 < len(parts):
            try:
                interval = int(parts[i + 1])
                i += 2
            except ValueError:
                return None, None
        else:
            i += 1

    if topology_file is None or interval is None:
        return None, None

    return topology_file, interval


def parse_update_command(command_line: str):
    """
    Parse: update <server-ID1> <server-ID2> <cost|inf>
    Returns (id1, id2, cost_str) or (None, None, None) if invalid.
    """
    parts = command_line.strip().split()
    if len(parts) != 4 or parts[0].lower() != "update":
        return None, None, None
    return parts[1], parts[2], parts[3]


def parse_disable_command(command_line: str) -> Optional[str]:
    """
    Parse: disable <server-ID>
    Returns server-ID or None if invalid.
    """
    parts = command_line.strip().split()
    if len(parts) != 2 or parts[0].lower() != "disable":
        return None
    return parts[1]


def parse_packets_command_args(command_line: str):
    """
    Parse: packets [on|off]
    Returns argument list to pass to handle_packets_command.
    """
    parts = command_line.strip().split()
    if len(parts) == 1:
        return ()
    if len(parts) == 2:
        return (parts[1],)
    # Extra args are considered invalid by handle_packets_command itself.
    return tuple(parts[1:])


###############################################################################
# Distance Vector packet (DV) receiver thread
###############################################################################

def _parse_dv_message(data: bytes) -> Optional[Dict[str, float]]:
    """
    Parse a DV message in the simple text framing used by sultan._send_updates_to_neighbors:
        line0: "DV <neighbor_id> <N>"
        line1: "<ip> <port>"
        next N lines: "<dest_id> <cost|inf>"

    Returns:
      dict with keys:
        'neighbor_id': str
        'vector': Dict[str, float]
    or None if malformed.
    """
    try:
        text = data.decode("utf-8").strip()
    except Exception:
        return None

    if not text:
        return None

    lines = text.splitlines()
    if len(lines) < 2:
        return None

    header = lines[0].split()
    if len(header) != 3 or header[0] != "DV":
        return None

    neighbor_id = header[1]
    try:
        n_entries = int(header[2])
    except ValueError:
        return None

    # We expect at least: header + addr-line + n_entries
    if len(lines) < 2 + n_entries:
        return None

    vec: Dict[str, float] = {}
    # lines[1] is "<ip> <port>" which we currently don't use
    for line in lines[2 : 2 + n_entries]:
        parts = line.split()
        if len(parts) != 2:
            return None
        dest_id, cost_str = parts
        try:
            cost = parse_cost(cost_str)
        except Exception:
            return None
        vec[dest_id] = cost

    return {"neighbor_id": neighbor_id, "vector": vec}


def _dv_receiver_loop(server: Server) -> None:
    """
    Background thread: receives DV packets via server's UDP socket and feeds
    them into Sultan's ingest_neighbor_vector, while also updating the packet
    counter for Bryson's PacketManager.
    """
    sock = server.get_socket()
    if sock is None:
        return

    # Ensure timeout so we can periodically check for exit conditions
    try:
        sock.settimeout(1.0)
    except Exception:
        pass

    while True:
        # Stop if the server has crashed or socket is gone
        if getattr(server, "crashed", False):
            break
        if server.get_socket() is None:
            break
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            continue
        except OSError:
            # Likely the socket was closed
            break
        except Exception:
            # Unexpected receive error; do not crash the thread
            continue

        parsed = _parse_dv_message(data)
        if not parsed:
            continue

        neighbor_id = parsed["neighbor_id"]
        vector = parsed["vector"]

        # Required by spec: print when we successfully receive a routing update
        print(f"RECEIVED A MESSAGE FROM SERVER {neighbor_id}")

        # Record packet for 'packets' command
        if hasattr(server, "packet_manager") and server.packet_manager is not None:
            server.packet_manager.record_packet(data, addr)

        try:
            ingest_neighbor_vector(server, neighbor_id, vector)
        except Exception:
            # Ignore DV processing errors to keep receiver alive
            continue


###############################################################################
# Main interactive loop
###############################################################################

def main() -> None:
    print("Distance Vector Routing Server (dv.py)")
    print("Commands:")
    print("  server -t <topology-file> -i <interval>")
    print("  display")
    print("  update <server-ID1> <server-ID2> <cost|inf>")
    print("  step")
    print("  packets [on|off]")
    print("  disable <server-ID>")
    print("  crash")
    print("  quit / exit\n")

    server_instance: Optional[Server] = None
    dv_receiver_thread: Optional[threading.Thread] = None

    try:
        while True:
            try:
                command = input("> ").strip()
            except EOFError:
                break
            except KeyboardInterrupt:
                print("\nExiting...")
                break

            if not command:
                continue

            # Global exit
            if command.lower() in ("quit", "exit"):
                break

            # server -t ... -i ...
            if command.startswith("server"):
                topology_file, interval = parse_server_command(command)
                if topology_file is None or interval is None:
                    print("Error: Invalid server command format.")
                    print("Usage: server -t <topology-file> -i <routing-update-interval>")
                    continue

                # Tear down existing server if any
                if server_instance is not None:
                    try:
                        stop_periodic_updates(server_instance)
                    except Exception:
                        pass
                    try:
                        server_instance.stop()
                    except Exception:
                        pass
                    server_instance = None

                # Start new server
                try:
                    srv = Server(topology_file, interval)
                    if not srv.start():
                        print("Error: Failed to start server.")
                        continue

                    # Attach runtime helpers
                    srv.packet_manager = PacketManager()

                    # Start periodic DV updates
                    start_periodic_updates(srv)

                    # Start receiver thread for incoming DV packets
                    dv_receiver_thread = threading.Thread(
                        target=_dv_receiver_loop, args=(srv,), daemon=True
                    )
                    dv_receiver_thread.start()

                    server_instance = srv

                    # Show initial routing table
                    server_instance.get_routing_table().print_table()
                    print("\nServer started successfully.")
                except Exception as e:
                    print(f"Error starting server: {e}")
                    server_instance = None
                continue

            # All other commands require a running server
            if server_instance is None:
                print(f"{command} ERROR SERVER NOT INITIALIZED")
                continue

            lower = command.lower()

            # display
            if lower == "display":
                print("display SUCCESS")
                server_instance.get_routing_table().display_table()
                continue

            # update <id1> <id2> <cost|inf>
            if lower.startswith("update"):
                sid1, sid2, cost_str = parse_update_command(command)
                if sid1 is None:
                    print(f"{command} INVALID FORMAT")
                    continue
                result = handle_update_command(server_instance, sid1, sid2, cost_str)
                print(result)
                continue

            # step
            if lower == "step":
                result = handle_step_command(server_instance)
                print(result)
                continue

            # packets [on|off]
            if lower.startswith("packets"):
                args = parse_packets_command_args(command)
                result = handle_packets_command(server_instance, *args)
                print(result)
                continue

            # disable <server-ID>
            if lower.startswith("disable"):
                neighbor_id = parse_disable_command(command)
                if neighbor_id is None:
                    print(f"{command} INVALID FORMAT")
                    continue

                neighbors = server_instance.get_neighbors()
                if neighbor_id not in neighbors:
                    print(f"{command} ERROR NOT A NEIGHBOR")
                    continue
                if neighbors[neighbor_id]["cost"] == INF:
                    print(f"{command} ERROR ALREADY DISABLED")
                    continue

                # Use Prince's helper to mark link as down locally
                if server_instance.disable_neighbor(neighbor_id):
                    # Re-run DV to propagate the effect into the full table
                    try:
                        # Reuse Sultan's update handler semantics (inf cost)
                        handle_update_command(
                            server_instance,
                            server_instance.server_id,
                            neighbor_id,
                            "inf",
                        )
                    except Exception:
                        pass
                    print(f"{command} SUCCESS")
                    print(f"Link to server {neighbor_id} disabled (cost set to infinity).")
                else:
                    print(f"{command} ERROR FAILED")
                continue

            # crash
            if lower == "crash":
                result = handle_crash_command(server_instance)
                print(result)
                # When crashed, stop periodic updates as well
                try:
                    stop_periodic_updates(server_instance)
                except Exception:
                    pass
                continue

            # Unknown command
            print(f"Unknown command: {command}")
            print("Valid commands: server, display, update, step, packets, disable, crash, quit/exit")

    finally:
        # Cleanup on exit
        if server_instance is not None:
            try:
                stop_periodic_updates(server_instance)
            except Exception:
                pass
            try:
                server_instance.stop()
            except Exception:
                pass


if __name__ == "__main__":
    main()
