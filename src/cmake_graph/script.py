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


def cli():
    graphs = pydot.graph_from_dot_data(dot_example)
    graph = graphs[0]
    graph.write_svg("example.svg")


if __name__ == "__main__":
    cli()
