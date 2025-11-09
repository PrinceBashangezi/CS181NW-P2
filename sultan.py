from typing import Any

INF = float('inf')


def parse_cost(cost_str: str) -> float:
    """
    Parse the link cost from the update command.
    Supports 'inf' (any case) to represent infinity.
    """
    cost_str = cost_str.strip()
    if cost_str.lower() == 'inf':
        return INF
    return float(int(cost_str))  # ensure integer input, store as float


def handle_update_command(server: Any,
                          server_id1: str,
                          server_id2: str,
                          cost_str: str) -> str:
    """
    Implements: update <server-ID1> <server-ID2> <Link Cost>

    This should be called when the user types:
        update 1 2 8
        update 1 2 inf

    server:    instance of prince.Server
    server_id1, server_id2: IDs given in the command
    cost_str:  new link cost (number or 'inf')

    Returns a status string: "<command-string> SUCCESS" or "<command-string> <error>".
    """

    command_string = f"update {server_id1} {server_id2} {cost_str}"

    # 1) parse cost
    try:
        new_cost = parse_cost(cost_str)
    except ValueError:
        return f"{command_string} INVALID COST"

    local_id = server.server_id

    # 2) if this server is not one of the endpoints, nothing to change locally
    if local_id != server_id1 and local_id != server_id2:
        # spec says the command will be issued to both endpoints separately,
        # so on "other" servers we can just acknowledge success
        return f"{command_string} SUCCESS"

    # 3) figure out which neighbor we are talking about
    neighbor_id = server_id2 if local_id == server_id1 else server_id1

    # get existing structures
    neighbors = server.neighbors              # dict: {neighbor_id: {'ip','port','cost'}}
    routing_table = server.get_routing_table()  # prince.RoutingTable instance
    all_servers = server.get_servers()        # dict of all known servers

    # 4) make sure neighbor exists in global server list
    if neighbor_id not in all_servers:
        return f"{command_string} UNKNOWN SERVER"

    # 5) update neighbors[] (link cost)
    if neighbor_id not in neighbors:
        # if it's a brand new neighbor (e.g., link created dynamically), add it
        neighbor_info = all_servers[neighbor_id]
        neighbors[neighbor_id] = {
            'ip':   neighbor_info['ip'],
            'port': neighbor_info['port'],
            'cost': new_cost,
        }
    else:
        neighbors[neighbor_id]['cost'] = new_cost

    # 6) update routing table entry for that neighbor
    if new_cost == INF:
        # disabling / breaking the link
        routing_table.update_entry(destination_id=neighbor_id,
                                   cost=INF,
                                   next_hop=None)
    else:
        # direct neighbor link with finite cost; next hop is the neighbor itself
        routing_table.update_entry(destination_id=neighbor_id,
                                   cost=new_cost,
                                   next_hop=neighbor_id)

    # NOTE: Full Bellman-Ford recomputation can be triggered here later if you
    # also have stored distance vectors from neighbors. For Week 1, just
    # updating the direct link and routing table entry is enough.

    return f"{command_string} SUCCESS"
