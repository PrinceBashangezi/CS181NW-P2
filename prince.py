import socket
import sys

class TopologyParser:
    """Parse topology file and extract server information"""
    
    @staticmethod
    def parse_topology_file(filename):
        """
        Parse topology file with format:
        <num-servers>
        <num-neighbors>
        <server-ID> <server-IP> <server-port>
        <server-ID1> <server-ID2> <cost>
        ...
        
        Returns:
            dict with keys: 'num_servers', 'num_neighbors', 'server_id', 
                           'server_ip', 'server_port', 'servers', 'neighbors'
        """
        try:
            with open(filename, 'r') as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
            if len(lines) < 3:
                raise ValueError("Topology file must have at least 3 lines")
            
            # Parse num-servers
            num_servers = int(lines[0])
            
            # Parse num-neighbors
            num_neighbors = int(lines[1])
            
            # Parse this server's info (server-ID, server-IP, server-port)
            server_info = lines[2].split()
            if len(server_info) != 3:
                raise ValueError("Server info line must have format: <server-ID> <server-IP> <server-port>")
            
            server_id = server_info[0]
            server_ip = server_info[1]
            server_port = int(server_info[2])
            
            # Parse all servers in network
            servers = {}
            server_idx = 3
            for i in range(num_servers-1):
                if server_idx >= len(lines):
                    raise ValueError(f"Not enough server entries in topology file (expected {num_servers})")
                
                server_line = lines[server_idx].split()
                if len(server_line) != 3:
                    raise ValueError(f"Server entry must have format: <server-ID> <server-IP> <server-port>")
                
                s_id = server_line[0]
                s_ip = server_line[1]
                s_port = int(server_line[2])
                servers[s_id] = {'ip': s_ip, 'port': s_port}
                server_idx += 1
            
            # Parse neighbor links (server-ID1, server-ID2, cost)
            neighbors = {}
            if server_idx + num_neighbors > len(lines):
                raise ValueError(f"Not enough neighbor entries in topology file (expected {num_neighbors})")
            
            for i in range(num_neighbors):
                neighbor_line = lines[server_idx].split()
                if len(neighbor_line) != 3:
                    raise ValueError(f"Neighbor entry must have format: <server-ID1> <server-ID2> <cost>")
                
                server_id1 = neighbor_line[0]
                server_id2 = neighbor_line[1]
                cost = int(neighbor_line[2])
                
                # Determine which neighbor this is (the one that's not this server)
                if server_id1 == server_id:
                    neighbor_id = server_id2
                elif server_id2 == server_id:
                    neighbor_id = server_id1
                else:
                    # This link doesn't involve this server, skip it
                    server_idx += 1
                    continue
                
                # Validate neighbor exists in servers list
                if neighbor_id not in servers:
                    raise ValueError(f"Neighbor {neighbor_id} not found in servers list")
                
                neighbors[neighbor_id] = {
                    'ip': servers[neighbor_id]['ip'],
                    'port': servers[neighbor_id]['port'],
                    'cost': cost
                }
                server_idx += 1
            
            return {
                'num_servers': num_servers,
                'num_neighbors': num_neighbors,
                'server_id': server_id,
                'server_ip': server_ip,
                'server_port': server_port,
                'servers': servers,
                'neighbors': neighbors
            }
        except FileNotFoundError:
            raise FileNotFoundError(f"Topology file '{filename}' not found")
        except ValueError as e:
            raise ValueError(f"Error parsing topology file: {e}")
        except Exception as e:
            raise Exception(f"Unexpected error reading topology file: {e}")


class RoutingTable:
    """Manage routing table for Distance Vector Routing"""
    
    def __init__(self, server_id, servers, neighbors):
        """
        Initialize routing table
        server_id: ID of this server
        servers: dict of all servers {server_id: {'ip': ..., 'port': ...}}
        neighbors: dict of neighbors {neighbor_id: {'ip': ..., 'port': ..., 'cost': ...}}
        """
        self.server_id = server_id
        self.table = {}
        
        # Initialize routing table
        # For self: cost = 0, next_hop = self
        self.table[server_id] = {
            'cost': 0,
            'next_hop': server_id
        }
        
        # For neighbors: cost = direct link cost, next_hop = neighbor
        for neighbor_id, neighbor_info in neighbors.items():
            self.table[neighbor_id] = {
                'cost': neighbor_info['cost'],
                'next_hop': neighbor_id
            }
        
        # For all other servers: cost = infinity, next_hop = None
        for s_id in servers:
            if s_id not in self.table:
                self.table[s_id] = {
                    'cost': float('inf'),
                    'next_hop': None
                }
    
    def get_cost(self, destination_id):
        """Get cost to destination"""
        if destination_id in self.table:
            return self.table[destination_id]['cost']
        return float('inf')
    
    def get_next_hop(self, destination_id):
        """Get next hop to destination"""
        if destination_id in self.table:
            return self.table[destination_id]['next_hop']
        return None
    
    def update_entry(self, destination_id, cost, next_hop):
        """Update routing table entry"""
        if destination_id not in self.table:
            self.table[destination_id] = {}
        self.table[destination_id]['cost'] = cost
        self.table[destination_id]['next_hop'] = next_hop
    
    def get_table(self):
        """Get full routing table"""
        return self.table.copy()
    
    def print_table(self):
        """Print routing table in readable format"""
        print(f"\nRouting Table for Server {self.server_id}:")
        print("-" * 60)
        print(f"{'Destination':<15} {'Cost':<15} {'Next Hop':<15}")
        print("-" * 60)
        
        for dest_id in sorted(self.table.keys()):
            entry = self.table[dest_id]
            cost_str = str(entry['cost']) if entry['cost'] != float('inf') else "inf"
            next_hop_str = str(entry['next_hop']) if entry['next_hop'] else "-"
            print(f"{dest_id:<15} {cost_str:<15} {next_hop_str:<15}")
        print("-" * 60)


class Server:
    """Distance Vector Routing Server"""
    
    def __init__(self, topology_file, routing_update_interval):
        """
        Initialize server from topology file
        topology_file: path to topology file
        routing_update_interval: time interval between routing updates in seconds
        """
        # Parse topology file
        topology = TopologyParser.parse_topology_file(topology_file)

        self.server_id = topology['server_id']
        self.server_ip = topology['server_ip']
        self.server_port = topology['server_port']
        self.servers = topology['servers']
        self.neighbors = topology['neighbors']
        self.num_servers = topology['num_servers']
        self.num_neighbors = topology['num_neighbors']
        self.routing_update_interval = routing_update_interval
        
        # Initialize routing table
        self.routing_table = RoutingTable(self.server_id, self.servers, self.neighbors)
        
        # Initialize UDP socket
        self.socket = None
        
        print(f"Server {self.server_id} initialized:")
        print(f"  IP: {self.server_ip}")
        print(f"  Port: {self.server_port}")
        print(f"  Neighbors: {list(self.neighbors.keys())}")
        print(f"  Routing Update Interval: {self.routing_update_interval} seconds")
    
    def start(self):
        """Start UDP server socket"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.bind((self.server_ip, self.server_port))
            self.socket.settimeout(1.0)  # 1 second timeout for non-blocking operations
            print(f"Server {self.server_id} started and listening on {self.server_ip}:{self.server_port}")
            return True
        except socket.error as e:
            print(f"Error starting server: {e}")
            return False
    
    def stop(self):
        """Stop server and close socket"""
        if self.socket:
            self.socket.close()
            self.socket = None
            print(f"Server {self.server_id} stopped")
    
    def get_socket(self):
        """Get UDP socket"""
        return self.socket
    
    def get_routing_table(self):
        """Get routing table instance"""
        return self.routing_table
    
    def get_neighbors(self):
        """Get neighbors dictionary"""
        return self.neighbors
    
    def get_servers(self):
        """Get all servers dictionary"""
        return self.servers
    
    def get_server_info(self):
        """Get this server's information"""
        return {
            'id': self.server_id,
            'ip': self.server_ip,
            'port': self.server_port
        }


def parse_server_command(command_line):
    """Parse server command: server -t <topology-file> -i <interval>"""
    parts = command_line.strip().split()
    
    if len(parts) < 5 or parts[0] != 'server':
        return None, None
    
    topology_file = None
    interval = None
    
    i = 1
    while i < len(parts):
        if parts[i] == '-t' and i + 1 < len(parts):
            topology_file = parts[i + 1]
            i += 2
        elif parts[i] == '-i' and i + 1 < len(parts):
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


def main():
    """Main function - start program and listen for server command"""
    print("Distance Vector Routing Server")
    print("Type 'server -t <topology-file> -i <interval>' to start the server")
    print("Type 'quit' or 'exit' to exit\n")
    
    server_instance = None
    
    try:
        while True:
            try:
                command = input("> ").strip()
                
                if not command:
                    continue
                
                if command.lower() in ['quit', 'exit']:
                    if server_instance:
                        server_instance.stop()
                    print("Exiting...")
                    break
                
                if command.startswith('server'):
                    # Parse server command
                    topology_file, interval = parse_server_command(command)
                    if topology_file is None or interval is None:
                        print("Error: Invalid server command format.")
                        print("Usage: server -t <topology-file> -i <routing-update-interval>")
                        continue
                    
                    # Stop existing server if running
                    if server_instance:
                        server_instance.stop()
                    
                    # Create and start new server
                    try:
                        server_instance = Server(topology_file, interval)
                        if server_instance.start():
                            # Print initial routing table
                            server_instance.get_routing_table().print_table()
                            print("\nServer started successfully.")
                        else:
                            print("Error: Failed to start server.")
                            server_instance = None
                    except Exception as e:
                        print(f"Error starting server: {e}")
                        server_instance = None
                else:
                    print(f"Unknown command: {command}")
                    print("Type 'server -t <topology-file> -i <interval>' to start the server")
                    print("Type 'quit' or 'exit' to exit")
            
            except EOFError:
                if server_instance:
                    server_instance.stop()
                break
            except KeyboardInterrupt:
                if server_instance:
                    server_instance.stop()
                print("\nExiting...")
                break
    
    except Exception as e:
        print(f"Error: {e}")
        if server_instance:
            server_instance.stop()
        sys.exit(1)


if __name__ == "__main__":
    main()

