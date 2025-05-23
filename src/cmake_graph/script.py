"""
Let's check how pydot works.
"""

import json
import logging
from glob import glob
from os.path import isfile, isdir, join, getctime
import pydot
from collections import defaultdict

logging.basicConfig(level=logging.INFO)

CMAKE_API_CLIENT_NAME = "targetgraph"
CMAKE_API_PATH = ".cmake/api/v1/"

node_shapes = defaultdict(lambda: "septagon")
node_shapes.update(
    {
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
    def __init__(self, json_fpath, project=None, directory=None):
        assert isfile(json_fpath)
        with open(json_fpath, "r") as f:
            self._json = json.load(f)

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


def cmake_build_config_graph(config: dict, reply_dir: str):
    cfg_name = config["name"]
    projects = config["projects"]
    directories = config["directories"]
    targets = config["targets"]

    targets_dict = {t_cfg["id"]: t_cfg for t_cfg in targets}

    graph = pydot.Dot(f"targetgraph-{cfg_name}", graph_type="digraph", bgcolor="white")

    for t_cfg in targets:
        directory = directories[t_cfg["directoryIndex"]]
        project = projects[t_cfg["projectIndex"]]

        t_json = t_cfg["jsonFile"]
        target = Target(join(reply_dir, t_json), project=project, directory=directory)

        # create the node and dependencies
        extra_info = []
        extra_info.append(f"type={target.type()}")
        extra_info.append(f"len(depends)={len(target.dependency_ids())}")
        extra_info.append(f"sources={'\n'.join(target.sources())}")

        t_name = target.target_name()
        target_node = pydot.Node(t_name, tooltip="\n".join(extra_info))
        if target.type() != "EXECUTABLE":
            target_node.set_shape(node_shapes[target.type()])
        graph.add_node(target_node)

        # can it add edges before other nodes are known?
        for t_id in target.dependency_ids():
            dep_name = targets_dict[t_id]["name"]
            dep_edge = pydot.Edge(t_name, dep_name, style="dashed")
            graph.add_edge(dep_edge)

    return graph


def cmake_api_process_reply(reply_dir: str):
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
        graph = cmake_build_config_graph(cfg, reply_dir)
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

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.command == "setup":
        cmake_api_setup_query(args.build)
        return

    assert isdir(args.build)

    # make the graph from the reply
    reply_dir = cmake_api_get_reply_dir(args.build)
    all_cfg_graphs = cmake_api_process_reply(reply_dir)
    for graph in all_cfg_graphs:
        graph.write_svg(f"{graph.get_name()}.svg")


if __name__ == "__main__":
    cmake_graph_cli()
