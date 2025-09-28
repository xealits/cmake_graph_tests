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

from cmake_graph.codemodel import Codemodel, Dependence

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

    def __init__(self, prefix = None):
        self._index = 0
        self._number = 0
        self._prefix = "" if prefix is None else prefix

    def next(self):
        if self._index > len(self.greek_letters):
            raise RuntimeError("ran out of letters!")

        if self._index >= len(self.greek_letters):
            self._number += 1
            self._index = 0

        letter = self.greek_letters[self._index]
        self._index += 1
        symbol = self._prefix + letter
        if self._number > 0:
            symbol += str(self._number)
        return symbol


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

cluster_names = GenerateLetters("cluster_")

class DepCluster:
    def __init__(self, targets, except_deps=set(), usage_threshold=0):
        assert isinstance(targets, set)
        assert isinstance(except_deps, set)

        dep_sets = []
        used_targets = set()
        for trg in targets:
            deps = trg.dependant_targets - except_deps
            if not deps or len(trg.dependant_targets) <= usage_threshold:
                continue

            used_targets.add(trg)
            dep_sets.append(deps)

        self._usage_threshold = usage_threshold
        self._except_deps = except_deps
        self._graph = None

        self.dependants = set() if len(dep_sets) == 0 else set.intersection(*dep_sets)
        self.targets = set() if len(self.dependants) == 0 else used_targets

    def score(self):
        # links saved
        all_cluster_links = len(self.targets) * len(self.dependants)
        return all_cluster_links #- (len(self.targets) + len(self.dependants))

    def add_trg(self, trg):
        if len(trg.dependant_targets) > self._usage_threshold:
            return DepCluster(self.targets.union({trg}), self._except_deps)

        else:
            return self

    def accumulate(self, trg):
        with_dep = self.add_trg(trg)
        if with_dep.score() > self.score():
            self.dependants = with_dep.dependants
            self.targets = with_dep.targets

    def contains(self, dep_link: Dependence):
        return dep_link.source in self.dependants and dep_link.to in self.targets

    def get_graph(self):
        if self._graph is not None:
            return self._graph

        target_addrs = []
        for target in self.targets:
            #proj_name = projects[target.project_index()].name()
            proj_name = target.project_name()
            t_marker = target.get_marker()
            assert t_marker is not None
            target_addrs.append((proj_name, target.target_name(), t_marker))
        target_addrs.sort(key=lambda addr: addr[0])

        tooltip = "users:\n"
        tooltip += "\n".join(str(trg.target_name()) for trg in self.dependants)

        tooltip += "\ntargets:\n"
        tooltip += "\n".join(
            f"{i:2} {tm} {pn}: {tn}" for i, (pn, tn, tm) in enumerate(target_addrs)
        )

        used_trgs = len(self.targets)
        used_by = len(self.dependants)
        cluster_node = pydot.Node(
            f"{cluster_names.next()} {used_trgs}x{used_by}",
            label=f"set of {used_trgs} targets that are used together by {used_by}",
            shape="circle",
            # style="invis",
            tooltip=tooltip,
        )
        cluster_node.set("class", "node")
        self._graph = cluster_node

        return self._graph

def find_cluster(targets, except_deps=set(), usage_threshold=0):
    assert isinstance(targets, set) and len(targets) > 0

    most_used_targets = sorted(targets, key=lambda trg: len(trg.dependant_targets), reverse=True)
    cluster = DepCluster({most_used_targets[0]}, except_deps, usage_threshold)

    for trg in most_used_targets[1:]:
        cluster.accumulate(trg)

    logging.info(f"try the flat case {len(except_deps)=}")
    # one dependant has many targets
    all_dependants = set.union(*[trg.dependant_targets for trg in targets]) - except_deps
    if not all_dependants:
        return cluster

    most_dependant = max(all_dependants, key=lambda trg: len(trg.dependency_targets))
    logging.info(f"{str(most_dependant)=} {len(most_dependant.dependency_targets)=}")
    within_targets = set.intersection(most_dependant.dependency_targets, targets)
    flat_cluster = DepCluster(within_targets, except_deps, usage_threshold)

    if flat_cluster.score() > cluster.score():
        logging.info(f"{flat_cluster.score()=} {len(flat_cluster.dependants)=} {len(flat_cluster.targets)=}")
        #logging.info(f"{[str(trg) for trg in flat_cluster.dependants]}")
        return flat_cluster

    return cluster

def find_all_clusters(targets, except_deps=set(), usage_threshold=0):
    assert isinstance(targets, set)

    cur_cluster = find_cluster(targets, except_deps, usage_threshold)
    logging.info(f"{cur_cluster.score()=} {len(cur_cluster.dependants)=} {len(cur_cluster.targets)=}")
    if cur_cluster.score() < usage_threshold ** 2:
        return []

    # split by covered dependants
    # look at other targets
    other_targets = targets - cur_cluster.targets
    # but make sure to stay within the dependants of the current cluster
    all_dependants = set.union(*[trg.dependant_targets for trg in targets])
    new_except_deps = all_dependants - cur_cluster.dependants

    logging.info("other targets")
    clusters_in_same_dependants = find_all_clusters(other_targets,
                                                    set.union(except_deps, new_except_deps),
                                                    usage_threshold)

    # and at other dependants
    logging.info("other dependants")
    clusters_in_other_dependants = find_all_clusters(targets,
                                                     set.union(except_deps, cur_cluster.dependants),
                                                     usage_threshold)

    return [cur_cluster] + clusters_in_same_dependants + clusters_in_other_dependants

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

        if "rocksdb_check" in t_name:
            print("AAAA")

        if skip_names and re.match(skip_names, t_name):
            if "rocksdb_check" in t_name:
                print("skipping rocksdb_check target")
            continue

        # targets.append(trg)

        directory = directories[trg.directory_index()]
        tgraph = trg.get_graph()
        directory.get_graph().add_node(tgraph)
        tgraph.set_shape(node_shapes[t_type])

    dependencies = []
    for dep in codemodel.dependencies:
        if skip_names and re.match(skip_names, dep.to.target_name()):
            continue
        if skip_names and re.match(skip_names, dep.source.target_name()):
            if "rocksdb_check" in dep.source.target_name():
                print("skipping rocksdb_check target in deps")
                # TODO: how come it is in dependencies, but there is no such target?
                # the root node targets are missing?
            continue
        dependencies.append(dep)

    # if there are many dependencies on a target
    # "embed" it into dependants: add a symbol to the label, or add special nodes etc
    frequent_dependencies = set()
    frequent_dependencies_inds = set()
    icon_generator = GenerateLetters()
    #deps_to = [dep.to for dep in dependencies]
    for t_ind, target in enumerate(targets):
        usage_count = len(target.dependant_targets)
        if usage_count > frequent_deps_threshold:
            frequent_dependencies.add(target)
            frequent_dependencies_inds.add(t_ind)
            icon = icon_generator.next()
            target.set_marker(icon, usage_count)
            # or use the node fontcolor

    #max_cluster = find_cluster(set(targets), usage_threshold=frequent_deps_threshold)
    #print(f"{max_cluster.score()=}")
    all_clusters = find_all_clusters(set(targets), usage_threshold=frequent_deps_threshold)

    #if all_clusters:
    #    max_cluster = all_clusters[0]

    #clusters = set(max_cluster)
    #cluster_nodes = set()
    #used_set_node = None
    #if all_clusters and max_cluster.score() > frequent_deps_threshold ** 2:
    for max_cluster in all_clusters:
        # create an extra node
        set_target_names = "\n".join(t.target_name() for t in max_cluster.targets)
        logging.info(f"creating a target set node for:\n{set_target_names}")

        # let's just add it to the top graph
        # root_graph.add_node(used_set_node)
        used_set_node = max_cluster.get_graph()
        root_project_cluster.add_node(used_set_node)

        # add edges from the cluster node
        # if some of cluster targets are contained in another cluster
        # then point at that one
        left_targets = set(max_cluster.targets)
        for other_cluster in all_clusters:
            if other_cluster is max_cluster:
                continue

            if all(trg in left_targets for trg in other_cluster.targets):
                dep_cluster = pydot.Edge(
                    used_set_node.get_name(),
                    other_cluster.get_graph().get_name(),
                    style="dotted",
                    # tooltip=edge_tooltip,
                    # lhead=lhead
                )
                dep_cluster.set("class", "edge")
                root_project_cluster.add_edge(dep_cluster)

                left_targets -= other_cluster.targets

        for target in left_targets:
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
    graphed_used_set_edges = set()
    for target, to, edge_graph, full_dep in dependencies:
        same_dir = target.directory_index() == to.directory_index()

        #if "CMakeLib" in target.target_name():
        #    print(f"{target.target_name()}")

        # check if the dependency belongs to one of clusters
        max_cluster = None
        for cluster in all_clusters:
            if target in cluster.dependants and to in cluster.targets:
                max_cluster = cluster
                break

        # if target.target_name() == "CMakeLib" and to.target_name() == "cmbzip2":
        #    logging.info()

        if max_cluster and not same_dir:
            edge_from = target.get_graph()
            edge_to = max_cluster.get_graph()

            used_set_edge = (edge_from, edge_to)

            if used_set_edge in graphed_used_set_edges:
                continue
            else:
                graphed_used_set_edges.add(used_set_edge)

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
        #if "CMakeLib" in target.target_name():
        #    print(f"{target.target_name()} deps: {dep_node_name}")

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
        logging.warning(f"did not find the stylesheet file {args.stylesheet}")

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
