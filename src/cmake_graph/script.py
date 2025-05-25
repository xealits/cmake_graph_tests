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

logging.basicConfig(level=logging.INFO)

CMAKE_API_CLIENT_NAME = "targetgraph"
CMAKE_API_PATH = ".cmake/api/v1/"
GRAPHVIZ_LAYOUT_DEFAULT = "dot"

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


def cmake_api_projects_directories_targets(codemodel_cfg: dict):
    return (
        codemodel_cfg["projects"],
        codemodel_cfg["directories"],
        codemodel_cfg["targets"],
    )


class Target:
    def __init__(self, json_fpath, codemodel_json, project=None, directory=None):
        assert isfile(json_fpath)
        with open(json_fpath, "r") as f:
            self._json = json.load(f)

        self._codemodel = codemodel_json
        self.project = project
        self.directory = directory

    def type(self):
        return self._json["type"]

    def sources(self):
        return [src["path"] for src in self._json.get("sources", [])]

    def cmake_lists(self):
        return self._json["backtraceGraph"]["files"]

    def dependency_ids(self):
        return [dep["id"] for dep in self._json.get("dependencies", [])]

    def target_id(self):
        return self._json["id"]

    def target_name(self):
        return self._json["name"]

    def project_index(self):
        return self._codemodel["projectIndex"]

    def target_install_paths(self):
        install = self._json.get("install")
        if install is None:
            return None
        prefix = install["prefix"]["path"]
        destinations = [d for d in install["destinations"]]
        return [join(prefix, d["path"]) for d in destinations]

    def make_graph(self):
        t_name = self.target_name()
        t_type = self.type()

        # create the node and dependencies
        extra_info = []
        extra_info.append(f"type={t_type}")
        extra_info.append(f"len(depends)={len(self.dependency_ids())}")
        installs = self.target_install_paths()
        if installs:
            extra_info.append(f"installs:\n{'\n'.join(installs)}")
        extra_info.append(f"sources:\n{'\n'.join(self.sources())}")

        target_node = pydot.Node(t_name, tooltip="\n".join(extra_info))
        target_node.set_shape(node_shapes[t_type])

        return target_node


def cmake_build_config_graph(
    config: dict,
    reply_dir: str,
    skip_types: str = "",
    skip_names: str = "",
    layout: str = GRAPHVIZ_LAYOUT_DEFAULT,
):
    cfg_name = config["name"]
    projects = config["projects"]
    directories = config["directories"]
    targets = config["targets"]

    targets_dict = {}  # {t_model["id"]: t_model for t_model in targets}

    graph = pydot.Dot(
        f"targetgraph-{cfg_name}",
        graph_type="digraph",
        bgcolor="white",
        layout=layout,
        compound=True,
    )

    project_graphs = []
    for pr in projects:
        pr_name = pr["name"]
        dir_sources = [directories[i]["source"] for i in pr["directoryIndexes"]]
        pr_graph = pydot.Cluster(
            # f"cluster_{pr_name}",
            pr_name,
            label=pr_name,
            tooltip="\n".join(dir_sources),
            bgcolor="white",
            layout=layout,
            style="dotted",
        )

        pr_parent_index = pr.get("parentIndex")
        project_graphs.append((pr_parent_index, pr_graph))

    for parent_index, pr_graph in project_graphs:
        if parent_index is None:
            graph.add_subgraph(pr_graph)
        else:
            project_graphs[parent_index][1].add_subgraph(pr_graph)

    for t_model in targets:
        directory = directories[t_model["directoryIndex"]]
        project_index = t_model["projectIndex"]
        project = projects[project_index]
        project_graph = project_graphs[project_index][1]

        t_json = t_model["jsonFile"]
        target = Target(
            join(reply_dir, t_json), t_model, project=project, directory=directory
        )
        targets_dict[target.target_id()] = target

        t_name = target.target_name()
        t_type = target.type()

        if skip_types and re.match(skip_types, t_type):
            continue

        if skip_names and re.match(skip_names, t_name):
            continue

        project_graph.add_node(target.make_graph())

    # can it add edges before other nodes are known?
    for target in targets_dict.values():
        project_index = target.project_index()
        project_graph = project_graphs[project_index][1]

        for t_id in target.dependency_ids():
            dep_target = targets_dict[t_id]
            dep_name = dep_target.target_name()
            dep_edge = pydot.Edge(target.target_name(), dep_name, style="dashed")

            if project_index == dep_target.project_index():
                project_graph.add_edge(dep_edge)
            else:
                graph.add_edge(dep_edge)

    return graph


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
    )
    for graph in all_cfg_graphs:
        graph.write_svg(f"{graph.get_name()}.svg")
        graph.write_raw(f"{graph.get_name()}.dot")


if __name__ == "__main__":
    cmake_graph_cli()
