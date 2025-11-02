# 1. Problem Statement

In this assignment you will implement a simplified version of the Distance Vector Routing Protocol. 
The protocol will be run on top of four servers/machines/laptops (behaving as routers) using UDP. Each 
server runs on a machine at a pre-defined port number. The servers should be able to output their 
forwarding tables along with the cost and should be robust to link changes. A server should send out 
routing  packets  only  in  the  following  two  conditions:  a)  periodic  update  and  b)  the  user  uses 
command asking for one. This is a little different from the original algorithm which immediately sends 
out update routing information when routing table changes.


## 3. Topology Establishment

In this programming assignment, you will use four servers/machines/laptops. The four machines are 
required to form a network topology as shown in Fig. 1. Each server is supplied with a topology 
file at startup that it uses to build its initial routing table. The topology file is local and contains the 
link cost to the neighbors. For all other servers in the network, the initial cost would be infinity. Each 
server can only read the topology file for itself. The entries of a topology file are listed below: 

```
• <num-servers> 
• <num-neighbors> 
• <server-ID> <server-IP> <server-port> 
• <server-ID1> <server-ID2> <cost> 
```
```
num-servers: total number of servers in the network. 
num-neighbors: the number of directly linked neighbors of the server. 
server-ID, server-ID1, server-ID2: a unique identifier for a server, which is assigned by you.   
cost: cost of a given link between a pair of servers. Assume that cost is an integer value.
```



# Week 1 Delegations (Nov 2 - Nov 9)
```
Prince: server (startup etc)
Bryson: crash, packets
Sultan: update
```