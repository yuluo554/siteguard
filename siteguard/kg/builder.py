"""轻量图数据结构（骨架期零依赖；M3 增加 networkx/pyvis 导出适配器）。

节点：id -> {"label", "type", **props}
边：  (src, relation, dst) 去重集合
"""

from collections import OrderedDict


class SimpleGraph:
    def __init__(self):
        self._nodes = OrderedDict()
        self._edges = OrderedDict()  # key=(src,rel,dst) -> {"src","relation","dst",**props}

    def add_node(self, node_id, label, node_type, **props):
        if node_id in self._nodes:
            self._nodes[node_id].update(props)
        else:
            self._nodes[node_id] = dict({"label": label, "type": node_type}, **props)
        return node_id

    def add_edge(self, src, relation, dst, **props):
        key = (src, relation, dst)
        if key not in self._edges:
            self._edges[key] = dict({"src": src, "relation": relation, "dst": dst}, **props)
        return key

    def has_node(self, node_id):
        return node_id in self._nodes

    def get_node(self, node_id):
        return self._nodes.get(node_id)

    def neighbors(self, node_id, relation=None):
        out = []
        for e in self._edges.values():
            if e["src"] == node_id and (relation is None or e["relation"] == relation):
                out.append((e["dst"], e["relation"]))
            elif e["dst"] == node_id and (relation is None or e["relation"] == relation):
                out.append((e["src"], e["relation"]))
        return out

    def node_count(self):
        return len(self._nodes)

    def edge_count(self):
        return len(self._edges)

    def stats(self):
        by_type = {}
        for n in self._nodes.values():
            by_type[n["type"]] = by_type.get(n["type"], 0) + 1
        by_rel = {}
        for e in self._edges.values():
            by_rel[e["relation"]] = by_rel.get(e["relation"], 0) + 1
        return {"node_count": self.node_count(), "edge_count": self.edge_count(),
                "nodes_by_type": by_type, "edges_by_relation": by_rel}

    def to_dict(self):
        return {"nodes": list(self._nodes.values()), "edges": list(self._edges.values())}
