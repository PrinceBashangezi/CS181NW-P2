# sultan.py — Project 2 (Distance Vector)
#
# what I implemented:
# - handle_update_command: updates a direct link cost on this router, then recomputes the full table
# - handle_step_command: sends one DV update right now
# - start_periodic_updates / stop_periodic_updates: background sender that pushes DV every interval
# - ingest_neighbor_vector: store a neighbor’s last DV and recompute
# - recompute_routes: Bellman–Ford over all destinations using my link costs + neighbors’ DVs

import threading, time
from typing import Dict, Optional
from prince import Server

INF = float('inf')

# I keep a tiny bit of runtime state on the Server object so I don’t have to modify Prince’s class.
def _ensure_state(server: Server) -> None:
    # last DV I heard from each neighbor: neighbor_id -> {dest_id: cost}
    if not hasattr(server, "dv_from_neighbor"):
        server.dv_from_neighbor: Dict[str, Dict[str, float]] = {}
    # last time I heard a DV from each neighbor: neighbor_id -> timestamp (seconds)
    if not hasattr(server, "dv_last_heard_time"):
        server.dv_last_heard_time: Dict[str, float] = {}
    # flags/handle for my periodic sender thread
    if not hasattr(server, "sultan_periodic_running"):
        server.sultan_periodic_running = False
    if not hasattr(server, "sultan_periodic_thread"):
        server.sultan_periodic_thread = None

# I accept integer costs and also "inf" to mean the link is disabled/unreachable.
def parse_cost(cost_str: str) -> float:
    s = cost_str.strip().lower()
    if s == "inf":
        return INF
    return float(int(cost_str))  # the handout uses ints; I store as float (no harm)

# recompute the whole routing table via Bellman–Ford
def recompute_routes(server: Server) -> None:
    _ensure_state(server)
    rt = server.get_routing_table()

    # the set of destinations I consider: me, all known servers, and any dests neighbors mentioned
    all_dests = {server.server_id, *server.get_servers().keys()}
    for vec in server.dv_from_neighbor.values():
        all_dests |= set(vec.keys())

    for d in all_dests:
        if d == server.server_id:
            # distance to self = 0, next hop is me
            rt.update_entry(d, 0.0, server.server_id)
            continue

        best_cost, best_hop = INF, None

        # first, check if d is a direct neighbor with a finite link cost
        neighbors = server.get_neighbors()
        if d in neighbors:
            direct_link = neighbors[d]["cost"]
            if direct_link != INF:
                best_cost, best_hop = direct_link, d

        # try going through each neighbor n
        for n, ninfo in neighbors.items():
            link = ninfo["cost"]  # cost to reach the neighbor
            if link == INF:
                continue          # link is down or disabled
            n_vec = server.dv_from_neighbor.get(n, {})
            n_cost_to_d = n_vec.get(d, INF)  # neighbor's cost to destination
            # If neighbor can't reach the destination (INF), don't use this path
            if n_cost_to_d == INF:
                continue
            via = link + n_cost_to_d  # cost to n + n's cost to d
            if via < best_cost:
                best_cost, best_hop = via, n

        # if I still don't have a path, mark unreachable
        if best_cost == INF:
            best_hop = None

        rt.update_entry(d, best_cost, best_hop)

# Send a link update notification to the other endpoint to ensure bidirectional symmetry
def _notify_link_update(server: Server, other_server_id: str, cost: float) -> None:
    """Send a link cost update message to the other endpoint to maintain A-B = B-A symmetry"""
    sock = server.get_socket()
    if sock is None:
        return
    
    all_servers = server.get_servers()
    if other_server_id not in all_servers:
        return
    
    other_info = all_servers[other_server_id]
    cost_str = "inf" if cost == INF else str(int(cost))
    
    # Send a LINK_UPDATE message: "LINK_UPDATE <from_id> <to_id> <cost>"
    message = f"LINK_UPDATE {server.server_id} {other_server_id} {cost_str}"
    
    try:
        sock.sendto(message.encode("utf-8"), (other_info["ip"], other_info["port"]))
    except Exception:
        # Silently fail - network issues shouldn't crash the update
        pass

# Handle incoming link update notification from another server
def handle_link_update_notification(server: Server, from_server_id: str, cost: float) -> None:
    """Process a link update notification from another server to maintain bidirectional symmetry"""
    _ensure_state(server)
    
    # Validate the sender is a known server
    all_servers = server.get_servers()
    if from_server_id not in all_servers:
        return
    
    # Update (or create) the neighbor entry's direct cost
    neighbors = server.get_neighbors()
    if from_server_id not in neighbors:
        info = all_servers[from_server_id]
        neighbors[from_server_id] = {"ip": info["ip"], "port": info["port"], "cost": cost}
    else:
        neighbors[from_server_id]["cost"] = cost
    
    # Keep the direct entry in the routing table consistent with the new cost
    rt = server.get_routing_table()
    if cost == INF:
        rt.update_entry(from_server_id, INF, None)
    else:
        rt.update_entry(from_server_id, cost, from_server_id)
    
    # Recompute routes after link change
    recompute_routes(server)

# update <server-ID1> <server-ID2> <cost|inf>
def handle_update_command(server: Server, server_id1: str, server_id2: str, cost_str: str) -> str:
    _ensure_state(server)
    cmd = f"update {server_id1} {server_id2} {cost_str}"

    # parse the new cost
    try:
        new_cost = parse_cost(cost_str)
    except Exception:
        return f"{cmd} INVALID COST"

    # if I'm not one of the endpoints, I just acknowledge
    me = server.server_id
    if me != server_id1 and me != server_id2:
        return f"{cmd} SUCCESS"

    # figure out which neighbor I'm updating
    neighbor_id = server_id2 if me == server_id1 else server_id1
    all_servers = server.get_servers()
    if neighbor_id not in all_servers:
        return f"{cmd} UNKNOWN SERVER"

    # update (or create) the neighbor entry's direct cost
    neighbors = server.get_neighbors()
    if neighbor_id not in neighbors:
        info = all_servers[neighbor_id]
        neighbors[neighbor_id] = {"ip": info["ip"], "port": info["port"], "cost": new_cost}
    else:
        neighbors[neighbor_id]["cost"] = new_cost

    # keep the direct entry in the routing table consistent with the new cost
    rt = server.get_routing_table()
    if new_cost == INF:
        rt.update_entry(neighbor_id, INF, None)
    else:
        rt.update_entry(neighbor_id, new_cost, neighbor_id)

    # Notify the other endpoint to update its view (ensures A-B = B-A)
    _notify_link_update(server, neighbor_id, new_cost)

    # after a link change, I recompute everything
    # Note: We do NOT clear the neighbor's distance vector here (only on timeout).
    # This allows finding alternative paths when disabling a direct link (e.g., A-B disabled
    # but A can still reach B via C). The recompute_routes function will find the best path.
    recompute_routes(server)
    return f"{cmd} SUCCESS"

# build my current DV as a dict {dest_id: cost}
# If neighbor_id is provided, implements split horizon with poison reverse:
# if our next hop to a destination is the neighbor, we advertise INF (poison reverse)
def _current_distance_vector(server: Server, neighbor_id: Optional[str] = None) -> Dict[str, float]:
    rt = server.get_routing_table()
    vec = {server.server_id: 0.0}
    for sid in server.get_servers().keys():
        cost = rt.get_cost(sid)
        # Split horizon with poison reverse: if sending to neighbor that is our next hop,
        # advertise INF to prevent count-to-infinity
        if neighbor_id is not None:
            next_hop = rt.get_next_hop(sid)
            if next_hop == neighbor_id:
                cost = INF  # Poison reverse
        vec[sid] = cost
    return vec

# send my DV to all neighbors with finite link cost (General Message format)
def _send_updates_to_neighbors(server: Server) -> None:
    sock = server.get_socket()
    if sock is None:
        raise RuntimeError("Server socket not started")

    for nid, info in server.get_neighbors().items():
        if info["cost"] == INF:
            continue
        vec = _current_distance_vector(server, neighbor_id=nid)
        
        # Build message in General Message format:
        # Number of update fields
        # Server port
        # Server IP
        # For each entry:
        #   Server IP address
        #   Server port
        #   0x0
        #   Server ID
        #   Cost
        all_servers = server.get_servers()
        lines = []  # Will build message first, then prepend count
        lines.append(str(server.server_port))  # Server port
        lines.append(server.server_ip)  # Server IP
        
        entry_count = 0
        for dest_id, cost in vec.items():
            # Get server info for this destination
            if dest_id == server.server_id:
                # For self, use our own IP and port
                dest_ip = server.server_ip
                dest_port = server.server_port
            elif dest_id in all_servers:
                dest_ip = all_servers[dest_id]["ip"]
                dest_port = all_servers[dest_id]["port"]
            else:
                # Unknown server, skip it
                continue
            
            lines.append(dest_ip)  # Server IP address
            lines.append(str(dest_port))  # Server port
            lines.append("0x0")  # 0x0 marker
            lines.append(dest_id)  # Server ID
            lines.append("inf" if cost == INF else str(int(cost)))  # Cost
            entry_count += 1
        
        # Prepend the number of update fields
        lines.insert(0, str(entry_count))
        
        data = ("\n".join(lines)).encode("utf-8")
        
        try:
            sock.sendto(data, (info["ip"], info["port"]))
        except Exception:
            # I don't want a flaky send to crash the process
            pass

## by Bryson
def _check_neighbor_timeouts(server: Server) -> None:
    """
    Implements the spec rule: if I do not receive a DV update from a neighbor
    for three consecutive routing intervals, I treat that neighbor as gone by
    setting the link cost to infinity (but keeping it in the table) and then
    recomputing routes.
    """
    _ensure_state(server)
    interval = getattr(server, "routing_update_interval", 5)
    if interval <= 0:
        return

    now = time.time()
    threshold = 3 * interval

    neighbors = server.get_neighbors()
    rt = server.get_routing_table()

    updated = False

    for nid, info in neighbors.items():
        # Only consider neighbors that are currently reachable (finite cost)
        if info.get("cost", INF) == INF:
            continue
        last = server.dv_last_heard_time.get(nid)
        if last is None:
            continue  # never heard from this neighbor yet
        if now - last >= threshold:
            # Mark the link as down
            info["cost"] = INF
            rt.update_entry(nid, INF, None)
            # Clear the neighbor's distance vector to avoid using stale information
            if nid in server.dv_from_neighbor:
                del server.dv_from_neighbor[nid]
            
            # Critical fix: Invalidate all routes that were using this neighbor as next hop
            # This prevents count-to-infinity when other neighbors have stale information
            table = rt.get_table()
            for dest_id, entry in table.items():
                if dest_id == server.server_id:
                    continue  # Skip self
                if entry.get('next_hop') == nid:
                    # This route was using the timed-out neighbor, mark as unreachable
                    rt.update_entry(dest_id, INF, None)
            
            updated = True

    if updated:
        recompute_routes(server)

# step: send one immediate routing packet
def handle_step_command(server: Server) -> str:
    try:
        _send_updates_to_neighbors(server)
        return "step SUCCESS"
    except Exception as e:
        return f"step ERROR {e}"

# periodic sender: fires every server.routing_update_interval seconds
def start_periodic_updates(server: Server) -> None:
    _ensure_state(server)
    if server.sultan_periodic_running:
        return
    interval = getattr(server, "routing_update_interval", 5)
    server.sultan_periodic_running = True

    def _loop():
        # send once right away, then every interval
        nxt = 0.0
        while server.sultan_periodic_running:
            now = time.time()
            if now >= nxt:
                try:
                    _send_updates_to_neighbors(server)
                except Exception:
                    pass
                nxt = now + interval
            # also periodically check for neighbors that have stopped sending DVs
            try:
                _check_neighbor_timeouts(server)
            except Exception:
                pass
            time.sleep(0.1)  # keep CPU usage low

    t = threading.Thread(target=_loop, daemon=True)
    server.sultan_periodic_thread = t
    t.start()

def stop_periodic_updates(server: Server) -> None:
    _ensure_state(server)
    server.sultan_periodic_running = False
    t = server.sultan_periodic_thread
    if t and t.is_alive():
        try:
            t.join(timeout=0.5)
        except Exception:
            pass

# called by my UDP receiver whenever I parse a DV from a neighbor
def ingest_neighbor_vector(server: Server, neighbor_id: str, vector: Dict[str, float]) -> None:
    _ensure_state(server)
    # store a copy so the caller can reuse its dict safely
    server.dv_from_neighbor[neighbor_id] = dict(vector)
    # remember when we last heard from this neighbor (for 3-interval timeout)
    server.dv_last_heard_time[neighbor_id] = time.time()
    recompute_routes(server)

