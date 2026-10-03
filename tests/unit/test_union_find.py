import random

from scout.dsa.union_find import UnionFind


def _bfs_components(nodes: list[int], edges: list[tuple[int, int]]) -> list[set[int]]:
    """Reference: connected components by breadth-first search."""
    adj: dict[int, set[int]] = {n: set() for n in nodes}
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)
    seen: set[int] = set()
    out: list[set[int]] = []
    for start in nodes:
        if start in seen:
            continue
        comp, queue = {start}, [start]
        seen.add(start)
        while queue:
            node = queue.pop()
            for nxt in adj[node] - seen:
                seen.add(nxt)
                comp.add(nxt)
                queue.append(nxt)
        out.append(comp)
    return out


def test_transitive_merge_across_sources() -> None:
    uf: UnionFind[str] = UnionFind()
    uf.union("fpl:500011", "understat:8801")
    uf.union("understat:8801", "tm:880011")
    uf.add("fpl:500012")
    assert uf.connected("fpl:500011", "tm:880011")
    assert not uf.connected("fpl:500011", "fpl:500012")
    groups = sorted(uf.groups(), key=len)
    assert groups == [{"fpl:500012"}, {"fpl:500011", "understat:8801", "tm:880011"}]
    assert len(uf) == 4 and "tm:880011" in uf


def test_union_is_idempotent() -> None:
    uf = UnionFind([1, 2])
    root = uf.union(1, 2)
    assert uf.union(2, 1) == root
    assert len(uf.groups()) == 1


def test_matches_bfs_reference_on_random_graphs() -> None:
    rng = random.Random(7)
    for _ in range(50):
        nodes = list(range(rng.randint(1, 60)))
        edges = [(rng.choice(nodes), rng.choice(nodes)) for _ in range(rng.randint(0, len(nodes)))]
        uf = UnionFind(nodes)
        for a, b in edges:
            uf.union(a, b)
        got = sorted(sorted(g) for g in uf.groups())
        expected = sorted(sorted(g) for g in _bfs_components(nodes, edges))
        assert got == expected
