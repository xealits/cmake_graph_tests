"""
Let's check how pydot works.
"""

import pydot

dot_example = """
graph my_graph {
    bgcolor="white";
    a [label="Foo2", tooltip="tools 🥂", comment = "com"];
    b [shape=circle];
    a -- b -- c [color=blue];
}
"""

json_example = {
    "targets": [
        {"name": "foo", "depends": ["bar", "baz"]},
        {"name": "bar", "depends": []},
        {"name": "baz", "depends": []},
    ]
}


def example_dot():
    graphs = pydot.graph_from_dot_data(dot_example)
    graph = graphs[0]
    graph.write_svg("example_dot.svg")


def cli():
    example_dot()

    graph = pydot.Dot("my_graph", graph_type="digraph", bgcolor="white")
    for tinfo in json_example["targets"]:
        extra_info = []
        extra_info.append(f"len(depends)={len(tinfo['depends'])}")

        tname = tinfo["name"]
        target_node = pydot.Node(tname, tooltip="\n".join(extra_info))
        graph.add_node(target_node)

        # can it add edges before other nodes are known?
        for dep_name in tinfo["depends"]:
            dep_edge = pydot.Edge(tname, dep_name, style="dashed")
            graph.add_edge(dep_edge)

    graph.write_svg("example_json.svg")


if __name__ == "__main__":
    cli()
