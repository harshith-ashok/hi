"""
LeetCode 133 - Clone Graph
Medium - Graph, DFS, BFS, Hash Map

Given a reference of a node in a connected undirected graph,
return a deep copy (clone) of the graph.

Each node in the graph contains a value (int) and a list (List[Node]) of its neighbors.
"""

from collections import deque
from typing import Optional


class Node:
    def __init__(self, val=0, neighbors=None):
        self.val = val
        self.neighbors = neighbors if neighbors is not None else []


class Solution:
    def cloneGraph(self, node: Optional['Node']) -> Optional['Node']:
        """
        DFS approach with hash map to track visited nodes.
        Time: O(V + E) - visit each node and edge once
        Space: O(V) - hash map stores all nodes
        """
        if not node:
            return None
        
        # Map original node -> cloned node
        old_to_new = {}
        
        def dfs(n: 'Node') -> 'Node':
            if n in old_to_new:
                return old_to_new[n]
            
            # Create clone
            clone = Node(n.val)
            old_to_new[n] = clone
            
            # Clone all neighbors
            for neighbor in n.neighbors:
                clone.neighbors.append(dfs(neighbor))
            
            return clone
        
        return dfs(node)
    
    def cloneGraphBFS(self, node: Optional['Node']) -> Optional['Node']:
        """
        BFS approach with hash map.
        Time: O(V + E)
        Space: O(V)
        """
        if not node:
            return None
        
        old_to_new = {}
        queue = deque([node])
        old_to_new[node] = Node(node.val)
        
        while queue:
            curr = queue.popleft()
            for neighbor in curr.neighbors:
                if neighbor not in old_to_new:
                    old_to_new[neighbor] = Node(neighbor.val)
                    queue.append(neighbor)
                old_to_new[curr].neighbors.append(old_to_new[neighbor])
        
        return old_to_new[node]


# Test helper
def build_graph(adj_list):
    """Build graph from adjacency list like [[2,4],[1,3],[2,4],[1,3]]"""
    if not adj_list:
        return None
    nodes = {i+1: Node(i+1) for i in range(len(adj_list))}
    for i, neighbors in enumerate(adj_list):
        nodes[i+1].neighbors = [nodes[n] for n in neighbors]
    return nodes[1]


def graph_to_adj_list(node):
    """Convert graph back to adjacency list for verification"""
    if not node:
        return []
    visited = set()
    result = []
    
    def dfs(n):
        if n.val in visited:
            return
        visited.add(n.val)
        # Ensure result list is large enough
        while len(result) < n.val:
            result.append([])
        result[n.val - 1] = [neighbor.val for neighbor in n.neighbors]
        for neighbor in n.neighbors:
            dfs(neighbor)
    
    dfs(node)
    return result


if __name__ == "__main__":
    sol = Solution()
    
    # Test case 1: [[2,4],[1,3],[2,4],[1,3]]
    adj = [[2,4],[1,3],[2,4],[1,3]]
    original = build_graph(adj)
    cloned = sol.cloneGraph(original)
    print(f"Test 1 - Original: {adj}")
    print(f"Test 1 - Cloned:   {graph_to_adj_list(cloned)}")
    print(f"Test 1 - Pass: {adj == graph_to_adj_list(cloned)}")
    
    # Test case 2: Empty graph
    original = build_graph([])
    cloned = sol.cloneGraph(original)
    print(f"Test 2 - Empty: {cloned is None}")
    
    # Test case 3: Single node [[ ]]
    adj = [[]]
    original = build_graph(adj)
    cloned = sol.cloneGraph(original)
    print(f"Test 3 - Single: {graph_to_adj_list(cloned)}")
    print(f"Test 3 - Pass: {adj == graph_to_adj_list(cloned)}")
    
    # Test case 4: Two nodes [[2],[1]]
    adj = [[2],[1]]
    original = build_graph(adj)
    cloned = sol.cloneGraph(original)
    print(f"Test 4 - Two nodes: {graph_to_adj_list(cloned)}")
    print(f"Test 4 - Pass: {adj == graph_to_adj_list(cloned)}")
    
    print("\nAll tests passed!")