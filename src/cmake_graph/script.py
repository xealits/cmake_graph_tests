"""
Let's check how pydot works.
"""

import json
import logging
from glob import glob
from os.path import isfile, isdir, join, getctime
import pydot
from collections import defaultdict
import re
from itertools import chain

from cmake_graph.codemodel import Codemodel

logging.basicConfig(level=logging.INFO)

CMAKE_API_CLIENT_NAME = "targetgraph"
CMAKE_API_PATH = ".cmake/api/v1/"
GRAPHVIZ_LAYOUT_DEFAULT = "dot"
GRAPHVIZ_COLOR_FOR_DIRECTORY = "#fcd5ce"

node_shapes = defaultdict(lambda: "septagon")
node_shapes.update(
    {
        "EXECUTABLE": "egg",
        "STATIC_LIBRARY": "octagon",
        "INTERFACE_LIBRARY": "pentagon",
        "SHARED_LIBRARY": "doubleoctagon",
        "OBJECT_LIBRARY": "hexagon",
        "MODULE_LIBRARY": "tripleoctagon",
        "UTILITY": "note",
    }
)


class GenerateLetters:
    # greek_codes   = chain(range(0x370, 0x3e2), range(0x3f0, 0x400))
    greek_codes = chain(range(0x3B1, 0x3CA), range(0x391, 0x3AA))
    greek_symbols = (chr(c) for c in greek_codes)
    greek_letters = [c for c in greek_symbols if c.isalpha()]

    def __init__(self):
        self._index = 0

    def next(self):
        if self._index > len(self.greek_letters):
            raise RuntimeError("ran out of letters!")

        letter = self.greek_letters[self._index]
        self._index += 1
        return letter


def cmake_api_setup_query(build_dir: str):
    from os import makedirs

    api_dir = join(build_dir, CMAKE_API_PATH)
    makedirs(api_dir, exist_ok=True)
    api_dir_query = join(api_dir, "query", f"client-{CMAKE_API_CLIENT_NAME}")
    makedirs(api_dir_query, exist_ok=True)
    # touch the query file for codemodel-v2 object
    with open(join(api_dir_query, "codemodel-v2"), "w") as _:
        pass


def cmake_api_get_reply_dir(build_dir: str):
    api_dir_reply = join(build_dir, CMAKE_API_PATH, "reply")
    assert isdir(api_dir_reply)
    return api_dir_reply


def cmake_api_configs(codemodel_fname: str):
    assert isfile(codemodel_fname)
    with open(codemodel_fname, "r") as f:
        codemodel = json.load(f)

    return codemodel["configurations"]


#def cmake_api_projects_directories_targets(codemodel_cfg: dict):
#    return (
#        codemodel_cfg["projects"],
#        codemodel_cfg["directories"],
#        codemodel_cfg["targets"],
#    )


def cmake_build_config_graph(
    cfg: dict,
    reply_dir: str,
    skip_types: str = "",
    skip_names: str = "",
    layout: str = GRAPHVIZ_LAYOUT_DEFAULT,
    perproject=True,
    frequent_deps_threshold=5,
    rankdir="LR",
):
    codemodel = Codemodel(reply_dir, cfg, perproject)

    root_graph = codemodel.root_graph
    root_graph.set_layout(layout)
    root_graph.set_rankdir(rankdir)
    root_project_cluster = None

    projects = codemodel.projects

    for proj in projects:
        parent_index = proj.parent_index()
        if parent_index is None:
            root_project_cluster = proj.get_graph()
            root_graph.add_subgraph(proj.get_graph())
        else:
            projects[parent_index].get_graph().add_subgraph(proj.get_graph())

    directories = codemodel.directories
    for directory in directories:
        dgraph = directory.get_graph()
        projects[directory.project_index()].get_graph().add_subgraph(
            dgraph
        )
        dgraph.set_bgcolor(GRAPHVIZ_COLOR_FOR_DIRECTORY)

    # TODO: check how this works?
    # I don't add a node to the directory graph
    # but won't it create and edge for this dependency later?
    # targets = []
    targets = codemodel.targets
    for trg in codemodel.targets:
        t_name = trg.target_name()
        t_type = trg.type()

        if skip_types and re.match(skip_types, t_type):
            continue

        if skip_names and re.match(skip_names, t_name):
            continue

        # targets.append(trg)

        directory = directories[trg.directory_index()]
        tgraph = trg.get_graph()
        directory.get_graph().add_node(tgraph)
        tgraph.set_shape(node_shapes[t_type])

    dependencies = codemodel.dependencies

    # if there are many dependencies on a target
    # "embed" it into dependants: add a symbol to the label, or add special nodes etc
    frequent_dependencies = set()
    frequent_dependencies_inds = set()
    icon_generator = GenerateLetters()
    deps_to = [dep.to for dep in dependencies]
    for t_ind, target in enumerate(targets):
        usage_count = deps_to.count(target)
        if usage_count > frequent_deps_threshold:
            frequent_dependencies.add(target)
            frequent_dependencies_inds.add(t_ind)
            icon = icon_generator.next()
            target.set_marker(icon, usage_count)
            # or use the node fontcolor

    # count usage of sub-sets
    # of dependencies
    subsets_count = {}
    for target in targets:
        # target_dep_set = set(targets[i] for i in target.dependency_indexes())
        target_dep_set = frozenset(target.dependency_indexes())
        target_freq_set = target_dep_set.intersection(frequent_dependencies_inds)
        if not target_freq_set:
            continue
        subsets_count.setdefault(target_freq_set, 0)
        subsets_count[target_freq_set] += 1

    # find only the largest set for now
    used_set_indexes = max(subsets_count, key=lambda t_set: subsets_count[t_set])
    logging.info(f"{used_set_indexes}")
    count = subsets_count[used_set_indexes]
    used_set = set(targets[i] for i in used_set_indexes)
    used_set_node = None
    if count > frequent_deps_threshold and len(used_set) > frequent_deps_threshold:
        # create an extra node
        set_target_names = "\n".join(t.target_name() for t in used_set)
        logging.info(f"creating a target set node for:\n{set_target_names}")

        target_addrs = []
        for target in used_set:
            proj_name = projects[target.project_index()].name()
            t_marker = target.get_marker()
            assert t_marker is not None
            target_addrs.append((proj_name, target.target_name(), t_marker))
        target_addrs.sort(key=lambda addr: addr[0])
        tooltip = "\n".join(
            f"{i:2} {tm} {pn}: {tn}" for i, (pn, tn, tm) in enumerate(target_addrs)
        )

        used_set_node = pydot.Node(
            "max_used_set",
            label=f"set of {len(used_set)} targets that are used together by {count}",
            shape="circle",
            # style="invis",
            tooltip=tooltip,
        )
        used_set_node.set("class", "node")

        # let's just add it to the top graph
        # root_graph.add_node(used_set_node)
        root_project_cluster.add_node(used_set_node)

        # add edges from the node
        for target in used_set:
            dep_edge = pydot.Edge(
                used_set_node.get_name(),
                target.get_graph().get_name(),
                style="dotted",
                # tooltip=edge_tooltip,
                # lhead=lhead
            )
            dep_edge.set("class", "edge")
            # root_graph.add_edge(dep_edge)
            root_project_cluster.add_edge(dep_edge)

    # make the Edges for the dependencies
    # make the per-project edges
    # and edges to the sets of frequent dependencies
    already_covered_full_proj_deps = set()
    used_set_edges = set()
    for target, to, edge_graph, full_dep in dependencies:
        same_dir = target.directory_index() == to.directory_index()

        edge_over_used_set = (
            used_set_node is not None and not same_dir and to in used_set
        )

        # if target.target_name() == "CMakeLib" and to.target_name() == "cmbzip2":
        #    logging.info()

        if edge_over_used_set:
            edge_from = target.get_graph()
            edge_to = used_set_node

            used_set_edge = (edge_from, edge_to)

            if used_set_edge in used_set_edges:
                continue
            else:
                used_set_edges.add(used_set_edge)

            dep_edge = pydot.Edge(
                edge_from.get_name(),
                edge_to.get_name(),
                style="dotted",
                # tooltip=edge_tooltip,
                # lhead=lhead
            )
            dep_edge.set("class", "edge")
            # edge_graph.add_edge(dep_edge)
            # graphviz pulls nodes into the graph where the edge is defined
            # so, since the max used node is in the root graph
            # the edge must be there:
            # root_graph.add_edge(dep_edge)
            root_project_cluster.add_edge(dep_edge)
            continue

        if to in frequent_dependencies and not same_dir and not full_dep:
            marker = to.get_marker()
            assert marker is not None
            target.add_dep_marker(marker)
            continue

        # not frequent dependencies get turned into edges

        # check if it's a full-project dep
        edge_style = "dashed"
        edge_tooltip = ""
        lhead = ""
        dep_node_name = to.get_graph().get_name()
        if full_dep:
            dep_proj_name = projects[to.project_index()].name()
            lhead = projects[to.project_index()].get_graph().get_name()
            edge_tooltip = f"all targets from\n{dep_proj_name}"
            dep_proj_ind = to.project_index()
            dep_node_name = projects[dep_proj_ind].get_project_node()

            if (target, dep_proj_ind) in already_covered_full_proj_deps:
                edge_style = "invis"
            else:
                already_covered_full_proj_deps.add((target, dep_proj_ind))

        dep_edge = pydot.Edge(
            target.target_name(),
            dep_node_name,
            style=edge_style,
            tooltip=edge_tooltip,
            lhead=lhead,
        )
        dep_edge.set("class", "edge")
        edge_graph.add_edge(dep_edge)

    return root_graph


def cmake_api_process_reply(reply_dir: str, **kwargs):
    """cmake_api_process_reply(reply_dir: str)

    return graphs for all configurations returned by the codemodel-v2
    """

    # find the latest index
    paths = glob(join(reply_dir, "index*"))
    files = [p for p in paths if isfile(p)]
    index_file = max(files, key=getctime)

    with open(index_file, "r") as f:
        index = json.load(f)

    my_reply = index["reply"][f"client-{CMAKE_API_CLIENT_NAME}"]
    codemodel_fname = my_reply["codemodel-v2"]["jsonFile"]
    full_fpath = join(reply_dir, codemodel_fname)
    assert isfile(full_fpath), f"not a file: {full_fpath}"

    # return target graphs for each config
    all_graphs = []
    for cfg in cmake_api_configs(full_fpath):
        graph = cmake_build_config_graph(cfg, reply_dir, **kwargs)
        all_graphs.append(graph)

    return all_graphs


def cmake_graph_cli():
    import argparse

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Graph CMake targets using file-api",
        epilog="""Examples:\ncmake_graph -S . -B build/""",
    )

    parser.add_argument(
        "command",
        type=str,
        choices=["setup", "graph"],
        help="command to execute: setup or graph",
    )
    parser.add_argument(
        "-B", "--build", default="./build/", help="build directory of a CMake project"
    )
    parser.add_argument(
        "-d", "--debug", action="store_true", help="DEBUG level of logging"
    )

    parser.add_argument(
        "--skip-types",
        type=str,
        default="",
        help="skip targets with types which match the regexp",
    )
    parser.add_argument(
        "--skip-names",
        type=str,
        default="",
        help="skip targets with names which match the regexp",
    )

    parser.add_argument(
        "--layout",
        type=str,
        default=GRAPHVIZ_LAYOUT_DEFAULT,
        help=f"graphviz layout engine ({GRAPHVIZ_LAYOUT_DEFAULT})",
    )

    parser.add_argument(
        "--frequent-deps-threshold",
        type=int,
        default=5,
        help=f"threshold to start embedding frequently used dependencies",
    )

    parser.add_argument(
        "--rankdir",
        type=str,
        default="LR",
        help=f"rankdir of the dot graph (LR, TB, BT, RL)",
    )

    parser.add_argument(
        "--no-perproject",
        action="store_true",
        help=f"don't merge per-project edges",
    )

    parser.add_argument(
        "--stylesheet",
        type=str,
        default="./dot.css",
        help=f"the CSS stylesheet files to embed into SVG",
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.command == "setup":
        cmake_api_setup_query(args.build)
        return

    assert isdir(args.build)

    # make the graph from the reply
    reply_dir = cmake_api_get_reply_dir(args.build)
    all_cfg_graphs = cmake_api_process_reply(
        reply_dir,
        skip_types=args.skip_types,
        skip_names=args.skip_names,
        layout=args.layout,
        perproject=not args.no_perproject,
        frequent_deps_threshold=args.frequent_deps_threshold,
        rankdir=args.rankdir,
    )

    stylesheet = None
    if isfile(args.stylesheet):
        with open(args.stylesheet, "r") as f:
            stylesheet = f"<style>\n{f.read()}\n</style>"
    else:
        logging.warn(f"did not find the stylesheet file {args.stylesheet}")

    for graph in all_cfg_graphs:
        graph.write_raw(f"{graph.get_name()}.dot")

        # graph.write_svg(f"{graph.get_name()}.svg")
        svg_text = graph.create_svg().decode("utf-8")
        # insert the style
        if stylesheet is not None:
            svg_tag_start = svg_text.find("<svg")
            svg_tag_end = svg_tag_start + svg_text[svg_tag_start:].find(">")
            svg_text = (
                svg_text[: svg_tag_end + 1] + stylesheet + svg_text[svg_tag_end + 1 :]
            )

        with open(f"{graph.get_name()}.svg", "w") as f:
            f.write(svg_text)


if __name__ == "__main__":
    cmake_graph_cli()
