"""
Let's check how pydot works.
"""

import json
import logging
from glob import glob
from os.path import isfile, isdir, join, getctime
import pydot
from collections import defaultdict, namedtuple
import re
from itertools import chain

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


def cmake_api_projects_directories_targets(codemodel_cfg: dict):
    return (
        codemodel_cfg["projects"],
        codemodel_cfg["directories"],
        codemodel_cfg["targets"],
    )


Dependence = namedtuple("Dependence", "source to graph full_dep")


class Project:
    def __init__(self, project_codemodel, codemodel):
        self._project_codemodel = project_codemodel
        self._codemodel = codemodel
        self._graph = None
        self._project_node = None

    def name(self):
        return self._project_codemodel["name"]

    def parent_index(self):
        return self._project_codemodel.get("parentIndex")

    def subproj_indexes(self):
        return self._project_codemodel["childIndexes"]

    def target_indexes(self):
        return self._project_codemodel["targetIndexes"]

    def directory_indexes(self):
        return self._project_codemodel["directoryIndexes"]

    def full_dependence(self, target):
        deps = target.dependency_indexes()
        return all(ind in deps for ind in self.target_indexes())

    def get_project_node(self):
        if self._graph is None:
            self._graph = self.get_graph()
        assert self._project_node is not None
        return self._project_node

    def get_graph(self, layout="dot", bgcolor="white", style="dotted"):
        if self._graph is not None:
            return self._graph

        pr_name = self.name()
        dir_sources = []
        for i in self.directory_indexes():
            dir_sources.append(self._codemodel["directories"][i]["source"])

        pr_graph = pydot.Cluster(
            # f"cluster_{pr_name}",
            pr_name,
            label=pr_name,
            tooltip="\n".join(dir_sources),
            bgcolor=bgcolor,
            layout=layout,
            style=style,
        )

        # add a dummy invisible node per cluster
        # in the case we need an edge pointing at the whole project
        # like when all targets of the project are used
        project_node = pydot.Node(
            f"PROJNODE_{pr_graph.get_name()}",
            label=self.name(),
            shape="point",
            style="invis",
        )
        pr_graph.add_node(project_node)
        self._project_node = project_node

        self._graph = pr_graph
        return self._graph


class Directory:
    def __init__(self, directory_codemodel, codemodel, reply_dir):
        self._directory_codemodel = directory_codemodel
        self._codemodel = codemodel
        self._graph = None

        json_fpath = join(reply_dir, directory_codemodel["jsonFile"])
        assert isfile(json_fpath)
        with open(json_fpath, "r") as f:
            self._json = json.load(f)

    def source(self):
        return self._directory_codemodel["source"]

    def subdir_indexes(self):
        return self._directory_codemodel["childIndexes"]

    def target_indexes(self):
        return self._directory_codemodel["targetIndexes"]

    def project_index(self):
        return self._directory_codemodel["projectIndex"]

    def full_dependence(self, target):
        deps = target.dependency_indexes()
        return all(ind in deps for ind in self.target_indexes())

    def get_graph(self, layout="dot"):
        if self._graph is not None:
            return self._graph

        dir_source = self.source()
        dir_graph = pydot.Cluster(
            dir_source,
            label=f"📁 {dir_source}",
            labeljust="l",
            bgcolor="yellow",
            layout=layout,
            style="dotted",
            penwidth=0,
        )

        self._graph = dir_graph
        return self._graph


class Target:
    def __init__(self, target_codemodel, codemodel, reply_dir):
        json_fpath = join(reply_dir, target_codemodel["jsonFile"])
        assert isfile(json_fpath)
        with open(json_fpath, "r") as f:
            self._json = json.load(f)

        self._target_codemodel = target_codemodel
        self._codemodel = codemodel
        self.project = codemodel["projects"][self.project_index()]
        self.directory = codemodel["directories"][self.directory_index()]
        self._label = self.target_name()
        self._graph = None
        self._marker = None
        self._usage_count = 0
        self._dep_markers = []

    def set_label(self, label):
        self._label = label

        if self._graph is None:
            return

        if self._dep_markers:
            graph_label = label + "\n" + " ".join(self._dep_markers)
        else:
            graph_label = label

        self._graph.set_label(graph_label)

    def add_dep_marker(self, dep_mark):
        self._dep_markers.append(dep_mark)
        self.set_label(self._label)

    def set_marker(self, marker, usage_count):
        self._marker = marker
        self._usage_count = usage_count
        self.set_label(f"@{marker}({usage_count}) {self._label}")

    def get_marker(self):
        return self._marker

    def type(self):
        return self._json["type"]

    def sources(self):
        return [src["path"] for src in self._json.get("sources", [])]

    def compile_groups(self):
        cmp_info = []
        sources = self.sources()
        for cmp in self._json.get("compileGroups", []):
            info = {
                "sources": [sources[i] for i in cmp["sourceIndexes"]],
                "includes": [i["path"] for i in cmp.get("includes", [])],
                "defines": [i["define"] for i in cmp.get("defines", [])],
            }
            cmp_info.append(info)
        return cmp_info

    def cmake_lists(self):
        return self._json["backtraceGraph"]["files"]

    def dependency_ids(self):
        return [dep["id"] for dep in self._json.get("dependencies", [])]

    def dependency_indexes(self):
        inds = []
        dep_ids = self.dependency_ids()
        for i, t_model in enumerate(self._codemodel["targets"]):
            if t_model["id"] in dep_ids:
                inds.append(i)
        return inds

    def target_id(self):
        return self._json["id"]

    def target_name(self):
        return self._json["name"]

    def project_index(self):
        return self._target_codemodel["projectIndex"]

    def directory_index(self):
        return self._target_codemodel["directoryIndex"]

    def target_install_paths(self):
        install = self._json.get("install")
        if install is None:
            return None
        prefix = install["prefix"]["path"]
        destinations = [d for d in install["destinations"]]
        return [join(prefix, d["path"]) for d in destinations]

    def find_cmake_define(self):
        bg = self._json["backtraceGraph"]
        def_commands = ("add_executable", "add_library")
        definitions = [
            (i, com) for i, com in enumerate(bg["commands"]) if com in def_commands
        ]
        if not definitions:
            return None

        assert len(definitions) == 1
        def_index, def_com = definitions[0]

        for node in bg["nodes"]:
            if node.get("command") == def_index:
                def_info = node
                break
        def_file = bg["files"][def_info["file"]]
        def_line = def_info["line"]

        return def_com, def_file, def_line

    def get_graph(self):
        if self._graph is not None:
            return self._graph

        t_name = self.target_name()
        t_type = self.type()

        # create the node and dependencies
        extra_info = []
        extra_info.append(f"type={t_type}")

        definition = self.find_cmake_define()
        if definition:
            com, fname, line = definition
            extra_info.append(f"{com} @ {fname}:{line}")

        extra_info.append(f"len(depends)={len(self.dependency_ids())}")
        dep_defs = []
        for dep_ind in self.dependency_indexes():
            dep_model = self._codemodel["targets"][dep_ind]
            dep_proj_ind = dep_model["projectIndex"]
            dep_proj_name = self._codemodel["projects"][dep_proj_ind]["name"]
            dep_defs.append(f"{dep_proj_name}: {dep_model["name"]}")
        extra_info.append("\n".join(["deps:"] + sorted(dep_defs)))

        installs = self.target_install_paths()
        if installs:
            extra_info.append(f"installs:\n{'\n'.join(installs)}")

        compile_groups = self.compile_groups()
        if compile_groups:
            extra_info.append("compile_groups:")
        for cmp in compile_groups:
            extra_info.append("\n".join(["includes:"] + cmp["includes"]))
            extra_info.append("\n".join(["defines:"] + cmp["defines"]))
            extra_info.append("\n".join(["sources:"] + cmp["sources"]))

        target_node = pydot.Node(
            t_name, label=self._label, tooltip="\n".join(extra_info)
        )
        target_node.set_shape(node_shapes[t_type])

        self._graph = target_node
        self.set_label(self._label)
        return self._graph


def cmake_build_config_graph(
    codemodel: dict,
    reply_dir: str,
    skip_types: str = "",
    skip_names: str = "",
    layout: str = GRAPHVIZ_LAYOUT_DEFAULT,
    perproject=True,
    frequent_deps_threshold=5,
):
    cfg_name = codemodel["name"]
    # projects = codemodel["projects"]
    # directories = codemodel["directories"]
    # targets = codemodel["targets"]

    graph = pydot.Dot(
        f"targetgraph-{cfg_name}",
        graph_type="digraph",
        bgcolor="white",
        layout=layout,
        compound=True,
        rankdir="LR",
    )

    projects = []
    for pr in codemodel["projects"]:
        projects.append(Project(pr, codemodel))

    for proj in projects:
        parent_index = proj.parent_index()
        if parent_index is None:
            graph.add_subgraph(proj.get_graph())
        else:
            projects[parent_index].get_graph().add_subgraph(proj.get_graph())

    directories = []
    for dir_model in codemodel["directories"]:
        directory = Directory(dir_model, codemodel, reply_dir)
        directories.append(directory)
        projects[directory.project_index()].get_graph().add_subgraph(
            directory.get_graph()
        )

    targets_dict = {}  # {t_model["id"]: t_model for t_model in targets}
    for t_model in codemodel["targets"]:
        target = Target(
            target_codemodel=t_model,
            codemodel=codemodel,
            reply_dir=reply_dir,
        )
        targets_dict[target.target_id()] = target

        t_name = target.target_name()
        t_type = target.type()

        if skip_types and re.match(skip_types, t_type):
            continue

        if skip_names and re.match(skip_names, t_name):
            continue

        directory = directories[target.directory_index()]
        directory.get_graph().add_node(target.get_graph())

    dependencies = []
    for target in targets_dict.values():
        project = projects[target.project_index()]
        target_dep_ids = target.dependency_ids()

        full_project_dependencies = set()
        for dep_id in target_dep_ids:
            # if dependencies include all targets of a project
            # then depend on the whole project
            # - add lhead=cluester name
            dep_target = targets_dict[dep_id]
            dep_proj = projects[dep_target.project_index()]
            dep_proj_id = dep_proj.get_graph().get_name()

            full_dep = dep_proj.full_dependence(target)

            edge_style = (
                "invis" if dep_proj_id in full_project_dependencies else "dashed"
            )
            logging.debug(
                f"check full deps: {target.target_name()} {dep_proj_id} in {full_project_dependencies}"
            )

            edge_tooltip = ""
            dep_name = dep_target.target_name()
            if (
                perproject
                and full_dep
                and target.project_index() != dep_target.project_index()
            ):
                dep_name = dep_proj.get_project_node().get_name()
                dep_proj_name = dep_proj.get_project_node().get_label()
                edge_tooltip = f"all targets from\n{dep_proj_name}"

            # dep_edge = pydot.Edge(
            #    target.target_name(), dep_name, style=edge_style, tooltip=edge_tooltip
            # )

            # if perproject and full_dep:
            #    dep_edge.set_lhead(dep_proj_id)
            #    full_project_dependencies.add(dep_proj_id)
            #    logging.debug(
            #        f"full deps now: {target.target_name()} {full_project_dependencies}"
            #    )

            if target.project_index() == dep_target.project_index():
                # project.get_graph().add_edge(dep_edge)
                graph_for_edge = project.get_graph()
            else:
                # graph.add_edge(dep_edge)
                graph_for_edge = graph

            dep = Dependence(
                target,
                dep_target,
                graph=graph_for_edge,
                full_dep=(perproject and full_dep),
            )
            dependencies.append(dep)

            logging.debug(
                f"Added node dep: {target.target_name()} {dep_name} : {target.dependency_indexes()} - {dep_proj.target_indexes()}"
            )

    # if there are many dependencies on a target
    # "embed" it into dependants: add a symbol to the label, or add special nodes etc
    frequent_dependencies = set()
    icon_generator = GenerateLetters()
    deps = [dep.to for dep in dependencies]
    for target in targets_dict.values():
        usage_count = deps.count(target)
        if usage_count > frequent_deps_threshold:
            frequent_dependencies.add(target)
            icon = icon_generator.next()
            target.set_marker(icon, usage_count)
            # or use the node fontcolor

    full_project_dependencies = set()
    for target, to, edge_graph, full_dep in dependencies:
        same_dir = target.directory_index() == to.directory_index()
        if to in frequent_dependencies and not same_dir:
            marker = to.get_marker()
            assert marker is not None
            target.add_dep_marker(marker)
            continue

        # not frequent dependencies get turned into edges

        # check if it's a full-project dep
        edge_style = "dashed"
        edge_tooltip = ""
        if full_dep:
            dep_proj_name = projects[to.project_index()].name()
            edge_tooltip = f"all targets from\n{dep_proj_name}"
            dep_proj_ind = to.project_index()

            if (target, dep_proj_ind) in full_project_dependencies:
                edge_style = "invis"
            else:
                full_project_dependencies.add((target, dep_proj_ind))

        dep_edge = pydot.Edge(
            target.target_name(),
            to.get_graph().get_name(),
            style=edge_style,
            tooltip=edge_tooltip,
        )
        edge_graph.add_edge(dep_edge)

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

    parser.add_argument(
        "--frequent-deps-threshold",
        type=int,
        default=5,
        help=f"threshold to start embedding frequently used dependencies",
    )

    parser.add_argument(
        "--no-perproject",
        action="store_true",
        help=f"don't merge per-project edges",
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
        frequent_deps_threshold=args.frequent_deps_threshold
    )
    for graph in all_cfg_graphs:
        graph.write_svg(f"{graph.get_name()}.svg")
        graph.write_raw(f"{graph.get_name()}.dot")


if __name__ == "__main__":
    cmake_graph_cli()
